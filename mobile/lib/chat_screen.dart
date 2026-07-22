import 'dart:convert';
import 'dart:io';

import 'package:audioplayers/audioplayers.dart';
import 'package:file_picker/file_picker.dart';
import 'package:flutter/material.dart';
import 'package:flutter_markdown/flutter_markdown.dart';
import 'package:path_provider/path_provider.dart';
import 'package:record/record.dart';

import 'design_screen.dart';
import 'edit_screen.dart';
import 'orders_screen.dart';
import 'films_screen.dart';

import 'api.dart';
import 'arena_view.dart';
import 'login_screen.dart';
import 'main.dart';

class AgentStep {
  AgentStep({required this.agent, required this.task, this.status = 'queued', this.preview});
  final String agent;
  final String task;
  String status; // queued | running | done
  String? preview;
}

class ChatMsg {
  ChatMsg({required this.role, required this.text, this.author});
  final String role; // 'user' | 'assistant'
  String text;
  String? author; // display label for user messages in team workspaces
  List<AgentStep>? steps;
  ArenaLiveState? arenaLive; // ⚔️ while the arena streams
  ArenaVerdict? arenaData; // ⚔️ final verdict (live or restored from meta)
  String? think; // 🧠 extended reasoning line
}

class Conversation {
  Conversation({required this.id, required this.title});
  final String id;
  final String title;
}

class Workspace {
  Workspace({required this.id, required this.name, this.owner = false});
  final String id;
  final String name;
  final bool owner;
}

class AttachedFile {
  AttachedFile({required this.id, required this.filename});
  final String id;
  final String filename;
}

class ChatScreen extends StatefulWidget {
  const ChatScreen({super.key});

  @override
  State<ChatScreen> createState() => _ChatScreenState();
}

class _ChatScreenState extends State<ChatScreen> {
  final _input = TextEditingController();
  final _scroll = ScrollController();
  final List<ChatMsg> _messages = [];
  final List<AttachedFile> _files = [];
  final _recorder = AudioRecorder();
  final _player = AudioPlayer();
  int _homeTab = 0; // 🏠 Grok-style home: 0 = Ask (chat), Imagine → creation studios
  List<Conversation> _conversations = [];
  String? _conversationId;
  String? _recordPath;
  bool _busy = false;
  bool _search = true;
  bool _agentMode = false;
  bool _arenaMode = false;
  bool _thinkOn = false;
  String _model = 'auto';
  bool _recording = false;
  // ---- teams
  List<Workspace> _workspaces = [];
  Workspace? _workspace; // null = personal chats
  Map<String, String> _authors = {}; // user_id → display label (team conversations)

  @override
  void initState() {
    super.initState();
    _loadConversations();
    _loadWorkspaces();
  }

  @override
  void dispose() {
    _recorder.dispose();
    _player.dispose();
    super.dispose();
  }

  Future<void> _loadConversations() async {
    try {
      if (_workspace == null) {
        final data = await Api.get('/conversations');
        setState(() {
          _conversations = [
            for (final c in (data as List)) Conversation(id: c['id'] as String, title: c['title'] as String),
          ];
        });
      } else {
        final data = await Api.get('/workspaces/${_workspace!.id}/conversations');
        setState(() {
          _conversations = [
            for (final c in (data['conversations'] as List))
              Conversation(id: c['id'] as String, title: '${c['author']}: ${c['title']}'),
          ];
          _authors = {
            for (final e in (data['authors'] as Map).entries) '${e.key}': '${e.value}',
          };
        });
      }
    } catch (_) {/* api down — drawer just stays empty */}
  }

  // ------------------------------------------------------------------ teams
  Future<void> _loadWorkspaces() async {
    try {
      final data = await Api.get('/workspaces');
      setState(() {
        _workspaces = [
          for (final w in (data['workspaces'] as List))
            Workspace(id: w['id'] as String, name: w['name'] as String, owner: w['owner'] as bool? ?? false),
        ];
      });
    } catch (_) {/* teams unavailable — drawer hides the section */}
  }

  void _selectWorkspace(Workspace? w) {
    Navigator.of(context).maybePop();
    setState(() {
      _workspace = w;
      _conversationId = null;
      _messages.clear();
      _files.clear();
      _authors = {};
    });
    _loadConversations();
  }

  Future<void> _joinInvite() async {
    final ctrl = TextEditingController();
    String? err;
    final joined = await showDialog<bool>(
      context: context,
      builder: (ctx) => StatefulBuilder(
        builder: (ctx, setDlg) => AlertDialog(
          backgroundColor: MoodColors.panel,
          title: const Text('Join a team'),
          content: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              TextField(
                controller: ctrl,
                decoration: const InputDecoration(hintText: 'Paste invite link or code'),
              ),
              if (err != null)
                Padding(
                  padding: const EdgeInsets.only(top: 8),
                  child: Text(err!, style: const TextStyle(color: Colors.redAccent, fontSize: 12)),
                ),
            ],
          ),
          actions: [
            TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('Cancel')),
            FilledButton(
              style: FilledButton.styleFrom(backgroundColor: MoodColors.accent, foregroundColor: Colors.black),
              onPressed: () async {
                var t = ctrl.text.trim();
                final m = RegExp(r'/join/([A-Za-z0-9_\-]+)').firstMatch(t);
                if (m != null) t = m.group(1)!;
                if (t.length < 8) {
                  setDlg(() => err = 'That does not look like an invite code.');
                  return;
                }
                try {
                  final res = await Api.post('/workspaces/join', {'token': t});
                  if (ctx.mounted) Navigator.pop(ctx, true);
                  final wsName = (res['workspace']?['name'] as String?) ?? 'workspace';
                  _toast(res['already_member'] == true ? 'Already a member' : 'Joined $wsName 🎉');
                } catch (e) {
                  setDlg(() => err = e.toString().replaceFirst('Exception: ', ''));
                }
              },
              child: const Text('Join'),
            ),
          ],
        ),
      ),
    );
    if (joined == true) _loadWorkspaces();
  }

  Future<void> _openConversation(String id) async {
    Navigator.of(context).maybePop(); // close the drawer
    setState(() {
      _conversationId = id;
      _messages.clear();
      _busy = true;
    });
    try {
      final data = await Api.get('/conversations/$id');
      if (data['authors'] is Map) {
        _authors = {
          for (final e in (data['authors'] as Map).entries) '${e.key}': '${e.value}',
        };
      }
      setState(() {
        _messages
          ..clear()
          ..addAll([
            for (final m in (data['messages'] as List))
              if (m['role'] == 'user' || m['role'] == 'assistant')
                ChatMsg(
                  role: m['role'] as String,
                  text: m['content'] as String,
                  author: (m['role'] == 'user' && _workspace != null && m['user_id'] != null)
                      ? _authors['${m['user_id']}']
                      : null,
                )
                  // ⚔️ restore arena verdicts + 🧠 thinking lines from persisted meta
                  ..arenaData = (m['meta'] is Map && (m['meta'] as Map)['mode'] == 'arena')
                      ? ArenaVerdict.fromMeta(m['meta'] as Map)
                      : null
                  ..think = _thinkLine(m['meta']),
          ]);
      });
      _scrollToBottom();
    } catch (_) {/* ignore */} finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  void _newChat() {
    Navigator.of(context).maybePop();
    setState(() {
      _conversationId = null;
      _messages.clear();
      _files.clear();
    });
  }

  Future<void> _send() async {
    final text = _input.text.trim();
    if ((text.isEmpty && _files.isEmpty) || _busy) return;
    _input.clear();
    await _sendMessage(text);
  }

  /// Core send path — also reused by ⚔️ rematch (replays the last question).
  Future<void> _sendMessage(String text, {bool rematch = false}) async {
    if (text.isEmpty || _busy) return;
    final useArena = _arenaMode || rematch;
    final fileIds = rematch ? <String>[] : _files.map((f) => f.id).toList();
    final assistant = ChatMsg(role: 'assistant', text: '');
    setState(() {
      _busy = true;
      _messages.add(ChatMsg(role: 'user', text: text));
      _messages.add(assistant);
      if (!rematch) _files.clear();
    });
    _scrollToBottom();
    final payload = {
      'conversation_id': _conversationId,
      'message': text,
      'files': _agentMode ? <String>[] : fileIds,
      'search': _search,
      'workspace_id': _workspace?.id, // personal chats send null — server ignores it
      'model': _model,
      'think': _thinkOn,
      'arena': useArena,
      if (rematch) 'rematch': true,
    };
    final endpoint = _agentMode && !rematch
        ? '/agents/stream'
        : useArena
            ? '/agents/arena/stream'
            : '/chat/stream';
    try {
      await for (final ev in Api.streamTo(endpoint, payload)) {
        switch (ev['type']) {
          case 'meta':
            _conversationId ??= ev['conversation_id'] as String?;
            break;
          case 'plan':
            setState(() {
              assistant.steps = [
                for (final st in (ev['steps'] as List? ?? []))
                  AgentStep(agent: st['agent'] as String? ?? 'agent', task: st['task'] as String? ?? ''),
              ];
            });
            break;
          case 'step_start':
            _markStep(ev, 'running');
            break;
          case 'step_done':
            _markStep(ev, 'done');
            break;
          case 'delta':
            setState(() => assistant.text += (ev['text'] as String?) ?? '');
            _scrollToBottom();
            break;
          case 'topic':
            setState(() {
              assistant.arenaLive = ArenaLiveState(
                topic: ev['topic'] as String?,
                brand: ev['brand'] as String?,
                rematch: ev['rematch'] == true,
              );
            });
            break;
          case 'warning':
            setState(() => assistant.arenaLive?.warnings.add('${ev['message'] ?? ''}'));
            break;
          case 'draft_start':
            setState(() => assistant.arenaLive?.startDraft('${ev['provider'] ?? '?'}'));
            break;
          case 'draft_delta':
            // cap repaints: count chars without storing the whole text twice
            final t = '${ev['text'] ?? ''}';
            if (t.isNotEmpty) {
              setState(() => assistant.arenaLive?.addDelta('${ev['provider'] ?? '?'}', t.length));
            }
            break;
          case 'draft_done':
            setState(() => assistant.arenaLive?.finishDraft('${ev['provider'] ?? '?'}'));
            break;
          case 'vote_cast':
            setState(() {
              assistant.arenaLive?.votes.add(ArenaBallot(
                provider: '${ev['provider'] ?? '?'}',
                vote: ev['vote'] as String?,
                rationale: '${ev['rationale'] ?? ''}',
                invalid: ev['invalid'] == true || ev['vote'] == null,
              ));
            });
            break;
          case 'arena_verdict':
            setState(() {
              assistant.arenaData = ArenaVerdict.fromEvent(ev);
              assistant.arenaLive = null;
            });
            break;
          case 'thinking':
            setState(() {
              final ms = ev['think_time_ms'];
              if (ms is num) assistant.think = '🧠 reasoned ${(ms / 1000).toStringAsFixed(1)}s';
            });
            break;
          case 'error':
            setState(() => assistant.text = '⚠️ ${ev['message'] ?? 'Something went wrong'}');
            break;
        }
      }
      if (assistant.text.isEmpty) {
        setState(() => assistant.text = '⚠️ Empty response');
      }
    } catch (e) {
      setState(() => assistant.text = '⚠️ ${e.toString().replaceFirst('Exception: ', '')}');
    } finally {
      setState(() => _busy = false);
      _loadConversations();
    }
  }

  /// 🧠 Persisted thinking line for restored messages (matches the live stream label).
  static String? _thinkLine(dynamic meta) {
    if (meta is! Map || meta['mode'] != 'chat+think') return null;
    final ms = meta['think_time_ms'];
    if (ms is num && ms > 0) {
      return '🧠 reasoned ${ms >= 1000 ? '${(ms / 1000).toStringAsFixed(1)}s' : '${ms}ms'}';
    }
    return '🧠 extended reasoning';
  }

  /// ⚔️ Rematch: resend the last user question; drafters try to beat the prior winner.
  Future<void> _rematch() async {
    final lastUser = _messages.lastWhere((m) => m.role == 'user',
        orElse: () => ChatMsg(role: 'user', text: ''));
    if (lastUser.text.isEmpty || _busy) return;
    final wasArena = _arenaMode;
    _arenaMode = true; // force the arena pipeline for this send
    await _sendMessage(lastUser.text, rematch: true);
    _arenaMode = wasArena;
  }

  static const _pickerModels = [
    ['auto', '🚀', 'Auto · best pick'],
    ['grok-3-mini', '⚡', 'grok-3-mini · cheapest'],
    ['grok-4-fast', '💨', 'S1 Mood-4-Fast · newest, 2M ctx'],
    ['grok-4', '👑', 'S1 Mood-4 · flagship (🧠 thinking)'],
    ['grok-code-fast-1', '💻', 'grok-code-fast-1 (🧠 thinking)'],
  ];

  Future<void> _showModelPicker() async {
    await showModalBottomSheet(
      context: context,
      backgroundColor: MoodColors.panel,
      shape: const RoundedRectangleBorder(borderRadius: BorderRadius.vertical(top: Radius.circular(20))),
      builder: (ctx) => StatefulBuilder(
        builder: (ctx, setSheet) => SafeArea(
          child: Padding(
            padding: const EdgeInsets.fromLTRB(16, 10, 16, 20),
            child: Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                const Text('Premium models', style: TextStyle(fontSize: 15, fontWeight: FontWeight.w700, color: Colors.white)),
                const SizedBox(height: 10),
                for (final m in _pickerModels)
                  ListTile(
                    dense: true,
                    contentPadding: EdgeInsets.zero,
                    leading: Text(m[1], style: const TextStyle(fontSize: 18)),
                    title: Text(m[2], style: const TextStyle(color: Colors.white70, fontSize: 13)),
                    trailing: _model == m[0] ? const Icon(Icons.check, color: MoodColors.accent, size: 18) : null,
                    onTap: () {
                      setState(() => _model = m[0]);
                      setSheet(() {});
                    },
                  ),
                const Divider(color: Colors.white12, height: 18),
                SwitchListTile(
                  dense: true,
                  contentPadding: EdgeInsets.zero,
                  activeColor: MoodColors.accent,
                  title: Text('🧠 Extended reasoning', style: TextStyle(color: (_model == 'auto' || _model == 'grok-4' || _model == 'grok-code-fast-1') ? Colors.white70 : Colors.white24, fontSize: 13)),
                  subtitle: const Text('S1 Mood-4 (or code models) only', style: TextStyle(color: Colors.white24, fontSize: 11)),
                  value: _thinkOn && (_model == 'auto' || _model == 'grok-4' || _model == 'grok-code-fast-1'),
                  onChanged: (_model == 'auto' || _model == 'grok-4' || _model == 'grok-code-fast-1')
                      ? (v) {
                          setState(() => _thinkOn = v);
                          setSheet(() {});
                        }
                      : null,
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }

  void _markStep(Map<String, dynamic> ev, String status) {
    final idx = ev['i'];
    if (idx is! int) return;
    setState(() {
      final steps = _messages.isEmpty ? null : _messages.last.steps;
      if (steps != null && idx < steps.length) {
        steps[idx].status = status;
        if (status == 'done') steps[idx].preview = ev['preview'] as String?;
      }
    });
  }

  // ------------------------------------------------------------------ files
  static const _audioExts = {'mp3', 'wav', 'm4a', 'ogg', 'opus', 'webm', 'flac'};

  Future<void> _attach() async {
    try {
      final result = await FilePicker.platform.pickFiles(withData: true);
      final f = result?.files.first;
      if (f == null || f.bytes == null) return;
      final ext = f.name.split('.').last.toLowerCase();
      if (_audioExts.contains(ext)) {
        await _analyzeAudio(f.bytes!, f.name);
        return;
      }
      final saved = await Api.postMultipart('/files', f.bytes!, f.name);
      setState(() => _files.add(AttachedFile(id: saved['id'] as String, filename: saved['filename'] as String)));
    } catch (e) {
      _toast('Upload failed: ${e.toString().replaceFirst('Exception: ', '')}');
    }
  }

  /// Audio pick → transcribe + AI analysis (lyrics / mood / "what song is this?"),
  /// landed as a normal exchange in the current conversation.
  Future<void> _analyzeAudio(List<int> bytes, String filename) async {
    if (_busy) return;
    setState(() => _busy = true);
    try {
      final res = await Api.analyzeAudio(bytes, filename, conversationId: _conversationId);
      _conversationId ??= res['conversation_id'] as String?;
      setState(() {
        _messages.add(ChatMsg(role: 'user', text: '🎵 $filename'));
        _messages.add(ChatMsg(role: 'assistant', text: res['analysis'] as String? ?? ''));
      });
      _scrollToBottom();
      _loadConversations();
    } catch (e) {
      _toast("Audio analysis failed: ${e.toString().replaceFirst('Exception: ', '')}");
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  // ------------------------------------------------------------------ voice
  Future<void> _toggleVoice() async {
    if (_busy) return;
    if (!_recording) {
      final granted = await _recorder.hasPermission();
      if (!granted) {
        _toast('Microphone permission denied');
        return;
      }
      final dir = await getTemporaryDirectory();
      _recordPath = '${dir.path}/mood_voice_${DateTime.now().millisecondsSinceEpoch}.m4a';
      await _recorder.start(const RecordConfig(encoder: AudioEncoder.aacLc), path: _recordPath!);
      setState(() => _recording = true);
      return;
    }
    final path = await _recorder.stop();
    setState(() {
      _recording = false;
      _busy = true;
    });
    try {
      final bytes = await File(path ?? _recordPath!).readAsBytes();
      final res = await Api.postMultipart(
        '/voice/chat',
        bytes,
        'voice.m4a',
        fields: {if (_conversationId != null) 'conversation_id': _conversationId!},
      );
      _conversationId ??= res['conversation_id'] as String?;
      setState(() {
        _messages.add(ChatMsg(role: 'user', text: '🎙️ ${res['transcript']}'));
        _messages.add(ChatMsg(role: 'assistant', text: res['reply'] as String? ?? ''));
      });
      _scrollToBottom();
      final audioB64 = res['audio_b64'] as String?;
      if (audioB64 != null && audioB64.isNotEmpty) {
        await _player.stop();
        await _player.play(BytesSource(base64Decode(audioB64)));
      }
      _loadConversations();
    } catch (e) {
      _toast('Voice failed: ${e.toString().replaceFirst('Exception: ', '')}');
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  void _toast(String msg) {
    ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(msg)));
  }

  void _scrollToBottom() {
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (_scroll.hasClients) {
        _scroll.animateTo(_scroll.position.maxScrollExtent + 200,
            duration: const Duration(milliseconds: 200), curve: Curves.easeOut);
      }
    });
  }
        Future<void> _deleteAccountDialog() async {
          final pw = TextEditingController();
          var busy = false;
          String? err;
          final ok = await showDialog<bool>(
            context: context,
            barrierDismissible: false,
            builder: (ctx) => StatefulBuilder(builder: (ctx, setSt) => AlertDialog(
              backgroundColor: MoodColors.panel,
              title: const Text('🗑 Delete account permanently?'),
              content: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.start, children: [
                const Text(
                  'This erases EVERYTHING — chats, uploads, designs, films, memory, plugin tokens, and teams you own. It cannot be undone.',
                  style: TextStyle(fontSize: 12, color: Colors.grey),
                ),
                const SizedBox(height: 12),
                TextField(
                  controller: pw,
                  obscureText: true,
                  decoration: const InputDecoration(hintText: 'Type your password to confirm'),
                ),
                if (err != null)
                  Padding(
                    padding: const EdgeInsets.only(top: 8),
                    child: Text(err!, style: const TextStyle(fontSize: 11, color: Colors.redAccent)),
                  ),
              ]),
              actions: [
                TextButton(onPressed: busy ? null : () => Navigator.pop(ctx, false), child: const Text('Keep my account')),
                FilledButton(
                  style: FilledButton.styleFrom(backgroundColor: Colors.red.shade700),
                  onPressed: busy
                      ? null
                      : () async {
                          if (pw.text.isEmpty) {
                            setSt(() => err = 'Enter your password');
                            return;
                          }
                          setSt(() { busy = true; err = null; });
                          try {
                            await Api.deleteMyAccount(pw.text);
                            if (ctx.mounted) Navigator.pop(ctx, true);
                          } catch (e) {
                            setSt(() { busy = false; err = '$e'; });
                          }
                        },
                  child: busy
                      ? const SizedBox(width: 16, height: 16, child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white))
                      : const Text('Delete forever'),
                ),
              ],
            )),
          );
          pw.dispose();
          if (ok == true && mounted) {
            await Api.setToken(null);
            if (!mounted) return;
            Navigator.of(context).pushAndRemoveUntil(
              MaterialPageRoute(builder: (_) => const LoginScreen()), (_) => false);
          }
        }


  Future<void> _logout() async {
    await Api.setToken(null);
    if (!mounted) return;
    Navigator.of(context).pushAndRemoveUntil(
      MaterialPageRoute(builder: (_) => const LoginScreen()),
      (_) => false,
    );
  }

  // 🏠 Ask | Imagine — the Grok-mirror tab pair in the top bar.
  Widget _modeTabs() {
    return Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        _homeTabLabel('Ask', _homeTab == 0, () => setState(() => _homeTab = 0)),
        const SizedBox(width: 20),
        _homeTabLabel('Imagine', false, () {
          Navigator.of(context).push(MaterialPageRoute(builder: (_) => const DesignScreen()));
        }),
      ],
    );
  }

  Widget _homeTabLabel(String label, bool active, VoidCallback onTap) {
    return GestureDetector(
      onTap: onTap,
      behavior: HitTestBehavior.opaque,
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          Text(label,
              style: TextStyle(
                  fontSize: 15,
                  fontWeight: active ? FontWeight.w700 : FontWeight.w500,
                  color: active ? Colors.white : Colors.grey.shade500)),
          const SizedBox(height: 3),
          Container(
            height: 2.5,
            width: 22,
            decoration: BoxDecoration(
                color: active ? Colors.white : Colors.transparent,
                borderRadius: BorderRadius.circular(2)),
          ),
        ],
      ),
    );
  }

  // display-name rule: users see S1 Mood-4 / S1 Mood-4-Fast, never raw vendor ids
  String _modelLabel() {
    final base = _model == 'grok-4-fast' ? 'S1 Mood-4-Fast' : 'S1 Mood-4';
    return _model == 'auto' ? '$base · auto' : base;
  }

  Widget _quickChip(IconData icon, String label, VoidCallback? onTap) {
    return Padding(
      padding: const EdgeInsets.only(right: 8),
      child: ActionChip(
        avatar: Icon(icon, size: 16, color: Colors.grey.shade400),
        label: Text(label, style: const TextStyle(fontSize: 12.5)),
        onPressed: onTap,
        backgroundColor: Colors.white.withOpacity(0.06),
        side: BorderSide(color: Colors.white.withOpacity(0.08)),
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(20)),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        // 🏠 Grok-clean top bar: hamburger = everything moved to the menu,
        // Ask | Imagine tabs centered, ⚔ Arena as the single right icon.
        automaticallyImplyLeading: false,
        leading: Builder(
          builder: (ctx) => IconButton(
            icon: const Icon(Icons.menu),
            tooltip: 'Menu — chats, studios, AI modes',
            onPressed: () => Scaffold.of(ctx).openDrawer(),
          ),
        ),
        centerTitle: true,
        titleSpacing: 0,
        title: _modeTabs(),
        actions: [
          IconButton(
            tooltip: '⚔️ Arena — models debate, S1 Mood-4 judges',
            icon: Icon(_arenaMode ? Icons.shield : Icons.shield_outlined,
                color: _arenaMode ? MoodColors.accent : Colors.grey[700]),
            onPressed: () => setState(() {
              _arenaMode = !_arenaMode;
              if (_arenaMode) _agentMode = false;
            }),
          ),
        ],
      ),
      drawer: Drawer(
        backgroundColor: MoodColors.panel,
        child: SafeArea(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              Padding(
                padding: const EdgeInsets.all(16),
                child: FilledButton.icon(
                  onPressed: _newChat,
                  icon: const Icon(Icons.add, size: 18),
                  label: const Text('New chat'),
                  style: FilledButton.styleFrom(
                    backgroundColor: MoodColors.accent,
                    foregroundColor: Colors.black,
                    shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
                  ),
                ),
              ),
              // ── AI modes (moved off the home bar for a Grok-clean home) ──
              const Padding(
                padding: EdgeInsets.fromLTRB(16, 10, 16, 0),
                child: Text('AI MODES', style: TextStyle(fontSize: 10, letterSpacing: 1.2, color: Colors.grey)),
              ),
              SwitchListTile.adaptive(
                dense: true,
                secondary: const Icon(Icons.smart_toy_outlined, size: 18),
                title: const Text('Agent team', style: TextStyle(fontSize: 13)),
                subtitle: const Text('planner → specialists → writer',
                    style: TextStyle(fontSize: 10, color: Colors.grey)),
                value: _agentMode,
                onChanged: (v) => setState(() {
                  _agentMode = v;
                  if (v) _arenaMode = false;
                }),
              ),
              SwitchListTile.adaptive(
                dense: true,
                secondary: const Icon(Icons.public, size: 18),
                title: const Text('Live search', style: TextStyle(fontSize: 13)),
                subtitle: const Text('cite fresh web sources in answers',
                    style: TextStyle(fontSize: 10, color: Colors.grey)),
                value: _search,
                onChanged: (v) => setState(() => _search = v),
              ),
              ListTile(
                dense: true,
                leading: const Icon(Icons.tune, size: 18),
                title: const Text('Model & reasoning', style: TextStyle(fontSize: 13)),
                subtitle: Text(_modelLabel(), style: const TextStyle(fontSize: 10, color: Colors.grey)),
                onTap: () {
                  Navigator.of(context).maybePop();
                  _showModelPicker();
                },
              ),
              // Teams: switch between personal chats and shared team workspaces,
              // or redeem an invite link/code.
              Theme(
                data: Theme.of(context).copyWith(dividerColor: Colors.transparent),
                child: ExpansionTile(
                  dense: true,
                  tilePadding: const EdgeInsets.symmetric(horizontal: 16),
                  childrenPadding: EdgeInsets.zero,
                  leading: Icon(
                    _workspace == null ? Icons.person_outline : Icons.group_outlined,
                    size: 18,
                  ),
                  title: Text(
                    _workspace?.name ?? 'Personal',
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    style: const TextStyle(fontSize: 14, fontWeight: FontWeight.w600),
                  ),
                  subtitle: Text(
                    _workspace == null ? 'Personal chats · switch to a team' : 'Team workspace · shared',
                    style: const TextStyle(fontSize: 10, color: Colors.grey),
                  ),
                  children: [
                    ListTile(
                      dense: true,
                      selected: _workspace == null,
                      leading: const Icon(Icons.person_outline, size: 16),
                      title: const Text('Personal', style: TextStyle(fontSize: 13)),
                      onTap: () => _selectWorkspace(null),
                    ),
                    for (final w in _workspaces)
                      ListTile(
                        dense: true,
                        selected: _workspace?.id == w.id,
                        leading: const Icon(Icons.group_outlined, size: 16),
                        title: Text(w.name, maxLines: 1, overflow: TextOverflow.ellipsis, style: const TextStyle(fontSize: 13)),
                        onTap: () => _selectWorkspace(w),
                      ),
                    ListTile(
                      dense: true,
                      leading: const Icon(Icons.link, size: 16),
                      title: const Text('Join with invite…', style: TextStyle(fontSize: 13)),
                      onTap: () {
                        Navigator.of(context).maybePop();
                        _joinInvite();
                      },
                    ),
                  ],
                ),
              ),
              Expanded(
                child: ListView.builder(
                  itemCount: _conversations.length,
                  itemBuilder: (context, i) {
                    final c = _conversations[i];
                    return ListTile(
                      dense: true,
                      selected: c.id == _conversationId,
                      title: Text(c.title, maxLines: 1, overflow: TextOverflow.ellipsis),
                      onTap: () => _openConversation(c.id),
                    );
                  },
                ),
              ),
              const Divider(height: 1, color: MoodColors.line),
              ListTile(
                leading: const Icon(Icons.movie_creation_outlined, size: 18),
                title: const Text('🎞 Films'),
                subtitle: const Text('Your storyboard movies', style: TextStyle(fontSize: 10, color: Colors.grey)),
                onTap: () {
                  Navigator.of(context).maybePop();
                  Navigator.of(context).push(MaterialPageRoute(builder: (_) => const FilmsScreen()));
                },
              ),
              ListTile(
                leading: const Icon(Icons.palette_outlined, size: 18),
                title: const Text('Design Studio', style: TextStyle(fontSize: 14)),
                onTap: () {
                  Navigator.of(context).pop();
                  Navigator.of(context).push(MaterialPageRoute(builder: (_) => const DesignScreen()));
                },
              ),
              ListTile(
                leading: const Icon(Icons.content_cut, size: 18),
                title: const Text('✂️ Auto-Edit', style: TextStyle(fontSize: 14)),
                subtitle: const Text('Upload a clip · edit by instruction', style: TextStyle(fontSize: 10, color: Colors.grey)),
                onTap: () {
                  Navigator.of(context).pop();
                  Navigator.of(context).push(MaterialPageRoute(builder: (_) => const EditScreen()));
                },
              ),
              ListTile(
                leading: const Icon(Icons.request_page_outlined, size: 18),
                title: const Text('🛍 Client Orders', style: TextStyle(fontSize: 14)),
                subtitle: const Text('Magic links clients order from', style: TextStyle(fontSize: 10, color: Colors.grey)),
                onTap: () {
                  Navigator.of(context).pop();
                  Navigator.of(context).push(MaterialPageRoute(builder: (_) => const OrdersScreen()));
                },
              ),
              ListTile(
                leading: const Icon(Icons.logout, size: 18),
                title: const Text('Sign out'),
                onTap: _logout,
              ),
              ListTile(
                leading: Icon(Icons.delete_forever_outlined, size: 18, color: Colors.red.shade400),
                title: Text('Delete account', style: TextStyle(fontSize: 14, color: Colors.red.shade300)),
                subtitle: const Text('Erase everything — required by the app stores',
                    style: TextStyle(fontSize: 10, color: Colors.grey)),
                onTap: () {
                  Navigator.of(context).maybePop();
                  _deleteAccountDialog();
                },
              ),
            ],
          ),
        ),
      ),
      body: Column(
        children: [
          if (_agentMode)
            Container(
              width: double.infinity,
              color: MoodColors.panel,
              padding: const EdgeInsets.symmetric(vertical: 4),
              child: const Text(
                '🤖 Agent team — planner, concurrent specialists, writer & critic',
                textAlign: TextAlign.center,
                style: TextStyle(fontSize: 11, color: Colors.grey),
              ),
            ),
          if (_workspace != null)
            Container(
              width: double.infinity,
              color: MoodColors.panel,
              padding: const EdgeInsets.symmetric(vertical: 4),
              child: Text(
                '👥 Team · ${_workspace!.name} — conversations shared with all members',
                textAlign: TextAlign.center,
                style: const TextStyle(fontSize: 11, color: Colors.grey),
              ),
            ),
          Expanded(
            child: _messages.isEmpty
                ? Center(
                    // 🏠 Grok-clean home: just the Mood AI mark as a watermark.
                    child: Opacity(
                      opacity: 0.10,
                      child: Image.asset('assets/icon/app_icon.png', width: 210),
                    ),
                  )
                : ListView.builder(
                    controller: _scroll,
                    padding: const EdgeInsets.all(12),
                    itemCount: _messages.length,
                    itemBuilder: (context, i) => _Bubble(
                          _messages[i],
                          canRematch: !_busy,
                          onRematch: _rematch,
                        ),
                  ),
          ),
          // 🏠 Quick-launch chips (Grok-style) — only on the clean empty home
          if (_messages.isEmpty)
            SizedBox(
              height: 46,
              child: ListView(
                scrollDirection: Axis.horizontal,
                padding: const EdgeInsets.symmetric(horizontal: 14),
                children: [
                  _quickChip(Icons.movie_creation_outlined, 'Create Videos', () {
                    Navigator.of(context).push(MaterialPageRoute(builder: (_) => const FilmsScreen()));
                  }),
                  _quickChip(Icons.palette_outlined, 'Create design', () {
                    Navigator.of(context).push(MaterialPageRoute(builder: (_) => const DesignScreen()));
                  }),
                  _quickChip(Icons.content_cut, 'Edit clip', () {
                    Navigator.of(context).push(MaterialPageRoute(builder: (_) => const EditScreen()));
                  }),
                  _quickChip(Icons.mic_none, 'Voice', _busy ? null : _toggleVoice),
                  _quickChip(Icons.tune, _modelLabel(), _showModelPicker),
                ],
              ),
            ),
          if (_files.isNotEmpty)
            SizedBox(
              height: 34,
              child: ListView.separated(
                scrollDirection: Axis.horizontal,
                padding: const EdgeInsets.symmetric(horizontal: 12),
                itemCount: _files.length,
                separatorBuilder: (_, __) => const SizedBox(width: 6),
                itemBuilder: (context, i) => Chip(
                  label: Text(_files[i].filename, style: const TextStyle(fontSize: 11)),
                  onDeleted: () => setState(() => _files.removeAt(i)),
                  visualDensity: VisualDensity.compact,
                ),
              ),
            ),
          SafeArea(
            top: false,
            child: Padding(
              padding: const EdgeInsets.fromLTRB(8, 4, 8, 12),
              child: Row(
                crossAxisAlignment: CrossAxisAlignment.end,
                children: [
                  IconButton(
                    icon: const Icon(Icons.attach_file, size: 20),
                    tooltip: 'Attach file',
                    onPressed: _busy ? null : _attach,
                  ),
                  Expanded(
                    child: TextField(
                      controller: _input,
                      minLines: 1,
                      maxLines: 5,
                      textInputAction: TextInputAction.send,
                      onSubmitted: (_) => _send(),
                      decoration: InputDecoration(
                        hintText: _agentMode ? 'Give the agent team a goal…' : 'Ask Mood anything…',
                      ),
                    ),
                  ),
                  IconButton(
                    icon: Icon(_recording ? Icons.stop : Icons.mic,
                        size: 20, color: _recording ? Colors.redAccent : null),
                    tooltip: _recording ? 'Stop & send' : 'Voice message',
                    onPressed: _busy && !_recording ? null : _toggleVoice,
                  ),
                  IconButton.filled(
                    onPressed: _busy ? null : _send,
                    style: IconButton.styleFrom(backgroundColor: MoodColors.accent),
                    icon: _busy
                        ? const SizedBox(
                            width: 18, height: 18, child: CircularProgressIndicator(strokeWidth: 2))
                        : const Icon(Icons.send, color: Colors.black, size: 20),
                  ),
                ],
              ),
            ),
          ),
        ],
      ),
    );
  }
}

class _Bubble extends StatelessWidget {
  const _Bubble(this.msg, {this.canRematch = false, this.onRematch});
  final ChatMsg msg;
  final bool canRematch; // arena verdict visible + screen not busy
  final VoidCallback? onRematch;

  @override
  Widget build(BuildContext context) {
    if (msg.role == 'user') {
      return Align(
        alignment: Alignment.centerRight,
        child: Container(
          margin: const EdgeInsets.only(bottom: 12, left: 48),
          padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
          decoration: BoxDecoration(
            color: MoodColors.accent.withOpacity(0.20),
            border: Border.all(color: MoodColors.accent.withOpacity(0.35)),
            borderRadius: BorderRadius.circular(16),
          ),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.end,
            mainAxisSize: MainAxisSize.min,
            children: [
              if (msg.author != null)
                Padding(
                  padding: const EdgeInsets.only(bottom: 3),
                  child: Text(
                    msg.author!,
                    style: const TextStyle(fontSize: 10, color: Colors.grey, fontWeight: FontWeight.w600),
                  ),
                ),
              Text(msg.text),
            ],
          ),
        ),
      );
    }
    return Container(
      margin: const EdgeInsets.only(bottom: 12),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          if (msg.steps != null && msg.steps!.isNotEmpty)
            Container(
              margin: const EdgeInsets.only(bottom: 8),
              padding: const EdgeInsets.all(10),
              decoration: BoxDecoration(
                color: MoodColors.panel,
                border: Border.all(color: MoodColors.line),
                borderRadius: BorderRadius.circular(12),
              ),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  const Text('🤖 Agent team', style: TextStyle(fontSize: 11, fontWeight: FontWeight.w600)),
                  const SizedBox(height: 6),
                  for (final s in msg.steps!)
                    Padding(
                      padding: const EdgeInsets.symmetric(vertical: 2),
                      child: Row(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text(s.status == 'done' ? '✅' : s.status == 'running' ? '⏳' : '▫️'),
                          const SizedBox(width: 6),
                          Expanded(
                            child: Text(
                              '${_icon(s.agent)} ${s.agent} — ${s.task}',
                              style: const TextStyle(fontSize: 11, color: Colors.grey),
                            ),
                          ),
                        ],
                      ),
                    ),
                ],
              ),
            ),
          if (msg.think != null)
            Padding(
              padding: const EdgeInsets.only(bottom: 4),
              child: Text(msg.think!, style: const TextStyle(fontSize: 11, color: MoodColors.accent)),
            ),
          if (msg.arenaLive != null || msg.arenaData != null)
            ArenaPanel(
              live: msg.arenaLive,
              verdict: msg.arenaData,
              onRematch: msg.arenaData != null && canRematch ? onRematch : null,
            ),
          msg.text.isEmpty
              ? const SizedBox(width: 16, height: 16, child: CircularProgressIndicator(strokeWidth: 2))
              : SelectionArea(
                  child: MarkdownBody(
                    data: msg.text,
                    styleSheet: MarkdownStyleSheet.fromTheme(Theme.of(context))
                        .copyWith(p: const TextStyle(fontSize: 15, height: 1.45)),
                  ),
                ),
        ],
      ),
    );
  }

  String _icon(String agent) => switch (agent) {
        'researcher' => '🔍',
        'coder' => '⌨️',
        'writer' => '✍️',
        'critic' => '🧐',
        _ => '🤖',
      };
}
