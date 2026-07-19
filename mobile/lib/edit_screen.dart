// ✂️ Auto-Edit (mobile) — upload a clip + a plain-English instruction.
//
// Mirrors the web ✂️ Media Lab panel: pick a video, describe the edit
// ("make it vertical, add subtitles, cut it to the beat"), 202-accept +
// 4s poll until done, preview in a lightweight player, share/save via the
// native sheet. Brand logo stamp toggle when the user owns a brand logo.
import 'dart:async';
import 'dart:io';

import 'package:file_picker/file_picker.dart';
import 'package:flutter/material.dart';
import 'package:path_provider/path_provider.dart';
import 'package:share_plus/share_plus.dart';
import 'package:video_player/video_player.dart';

import 'api.dart';
import 'main.dart' show MoodColors;

class EditScreen extends StatefulWidget {
  const EditScreen({super.key});

  @override
  State<EditScreen> createState() => _EditScreenState();
}

class _EditScreenState extends State<EditScreen> {
  static const _examples = <String>[
    'make it vertical for tiktok with subtitles',
    'cut it to the beat of the music',
    'trim to the first 12 seconds, warm colors, my logo',
    'mute it and add a soft music bed',
  ];

  final _instruction = TextEditingController();
  File? _picked;
  String? _pickedName;
  bool _useBrand = false;
  bool _busy = false;
  String? _status; // live pipeline status line
  List<Map<String, dynamic>> _edits = [];
  Timer? _timer;

  @override
  void initState() {
    super.initState();
    _refresh();
    _timer = Timer.periodic(const Duration(seconds: 6), (_) {
      if (_edits.any((e) => e['status'] == 'queued' || e['status'] == 'running')) {
        _refresh(quiet: true);
      }
    });
  }

  @override
  void dispose() {
    _timer?.cancel();
    _instruction.dispose();
    super.dispose();
  }

  Future<void> _refresh({bool quiet = false}) async {
    try {
      final res = await Api.get('/media/edits');
      if (!mounted) return;
      setState(() => _edits = ((res['edits'] as List?) ?? []).cast<Map<String, dynamic>>());
    } catch (e) {
      if (!quiet && mounted) setState(() => _status = '$e');
    }
  }

  Future<void> _pick() async {
    final r = await FilePicker.platform.pickFiles(type: FileType.video);
    final path = r?.files.single.path;
    if (path == null) return;
    setState(() {
      _picked = File(path);
      _pickedName = r!.files.single.name;
    });
  }

  Future<void> _submit() async {
    if (_busy) return;
    final file = _picked;
    final text = _instruction.text.trim();
    if (file == null || text.length < 3) return;
    setState(() {
      _busy = true;
      _status = '⬆️ Uploading clip…';
    });
    try {
      final bytes = await file.readAsBytes();
      final res = await Api.postMultipart('/media/edits', bytes, _pickedName ?? 'clip.mp4',
          fields: {'instruction': text, 'use_brand': '$_useBrand'});
      final edit = (res['edit'] as Map?)?.cast<String, dynamic>();
      final id = '${edit?['id'] ?? ''}';
      if (id.isEmpty) throw Exception('no edit id returned');
      setState(() => _status = '✂️ Editing — planning stages & rendering…');
      // poll until done/failed (202-ack + poll pattern, like the web)
      for (var i = 0; i < 60; i++) {
        await Future.delayed(const Duration(seconds: 4));
        final e = await Api.get('/media/edits/$id');
        final st = '${e['status']}';
        if (st == 'done') {
          setState(() => _status = '🎬 Edit ready — see it below!');
          break;
        }
        if (st == 'failed') {
          setState(() => _status = '⚠️ ${e['note'] ?? 'edit failed'}');
          break;
        }
        if (mounted) setState(() => _status = '✂️ Rendering… (${i * 4}s)');
      }
      _picked = null;
      _instruction.clear();
      _refresh(quiet: true);
    } catch (e) {
      setState(() => _status = '⚠️ $e');
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _open(Map<String, dynamic> e) async {
    final url = e['url'] as String?;
    if (e['status'] != 'done' || url == null) return;
    try {
      setState(() => _status = '⬇️ Fetching your edit…');
      final bytes = await Api.getBytes(url);
      final dir = await getTemporaryDirectory();
      final path = '${dir.path}/mood-edit-${'${e['id']}'.substring(0, 8)}.mp4';
      await File(path).writeAsBytes(bytes, flush: true);
      if (!mounted) return;
      setState(() => _status = null);
      showModalBottomSheet(
        context: context,
        isScrollControlled: true,
        backgroundColor: MoodColors.panel,
        builder: (_) => _EditPlayer(path: path),
      );
    } catch (err) {
      setState(() => _status = '⚠️ $err');
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('✂️ Auto-Edit')),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          const Text('Upload a clip · tell Mood what to do in plain English',
              style: TextStyle(fontSize: 12, color: Colors.grey)),
          const SizedBox(height: 12),
          OutlinedButton.icon(
            onPressed: _busy ? null : _pick,
            icon: Icon(_picked == null ? Icons.video_library_outlined : Icons.check_circle_outline,
                size: 18, color: _picked == null ? null : Colors.greenAccent),
            label: Text(_pickedName ?? 'Pick a video from your gallery',
                maxLines: 1, overflow: TextOverflow.ellipsis),
            style: OutlinedButton.styleFrom(
              padding: const EdgeInsets.symmetric(vertical: 14, horizontal: 14),
              side: const BorderSide(color: MoodColors.line),
              alignment: Alignment.centerLeft,
            ),
          ),
          const SizedBox(height: 10),
          TextField(
            controller: _instruction,
            maxLines: 2,
            maxLength: 1000,
            decoration: const InputDecoration(
              hintText: 'e.g. make it vertical for tiktok, add subtitles, cut it to the beat…',
              counterText: '',
            ),
          ),
          const SizedBox(height: 4),
          Wrap(
            spacing: 6,
            children: [
              for (final x in _examples)
                ActionChip(
                  label: Text(x, style: const TextStyle(fontSize: 10)),
                  onPressed: () => _instruction.text = x,
                ),
            ],
          ),
          SwitchListTile(
            dense: true,
            contentPadding: EdgeInsets.zero,
            value: _useBrand,
            onChanged: (v) => setState(() => _useBrand = v),
            title: const Text('⭐ Stamp my brand logo', style: TextStyle(fontSize: 13)),
          ),
          const SizedBox(height: 6),
          FilledButton.icon(
            onPressed: (_busy || _picked == null || _instruction.text.trim().length < 3) ? null : _submit,
            icon: _busy
                ? const SizedBox(width: 16, height: 16, child: CircularProgressIndicator(strokeWidth: 2))
                : const Icon(Icons.auto_fix_high, size: 18),
            label: Text(_busy ? 'Working…' : 'Edit my video'),
            style: FilledButton.styleFrom(
              backgroundColor: MoodColors.accent,
              foregroundColor: Colors.black,
              padding: const EdgeInsets.symmetric(vertical: 14),
              shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
            ),
          ),
          if (_status != null) ...[
            const SizedBox(height: 10),
            Text(_status!, style: const TextStyle(fontSize: 12, color: MoodColors.accent)),
          ],
          const SizedBox(height: 16),
          if (_edits.isNotEmpty)
            const Text('Your edits', style: TextStyle(fontSize: 13, fontWeight: FontWeight.w600)),
          const SizedBox(height: 6),
          for (final e in _edits)
            Card(
              color: MoodColors.panel,
              margin: const EdgeInsets.only(bottom: 8),
              shape: RoundedRectangleBorder(
                  borderRadius: BorderRadius.circular(12), side: const BorderSide(color: MoodColors.line)),
              child: ListTile(
                dense: true,
                onTap: () => _open(e),
                leading: Icon(
                  switch ('${e['status']}') {
                    'done' => Icons.play_circle_outline,
                    'failed' => Icons.error_outline,
                    _ => Icons.hourglass_top,
                  },
                  color: switch ('${e['status']}') {
                    'done' => Colors.greenAccent,
                    'failed' => Colors.redAccent,
                    _ => Colors.amberAccent,
                  },
                ),
                title: Text('${e['instruction']}', maxLines: 2, overflow: TextOverflow.ellipsis,
                    style: const TextStyle(fontSize: 13)),
                subtitle: (e['note'] as String?)?.isNotEmpty == true
                    ? Text('${e['note']}', maxLines: 1, overflow: TextOverflow.ellipsis,
                        style: const TextStyle(fontSize: 10, color: Colors.grey))
                    : null,
                trailing: Text('${e['status']}', style: const TextStyle(fontSize: 10, color: Colors.grey)),
              ),
            ),
        ],
      ),
    );
  }
}

/// Lightweight result player + share-sheet export.
class _EditPlayer extends StatefulWidget {
  const _EditPlayer({required this.path});
  final String path;

  @override
  State<_EditPlayer> createState() => _EditPlayerState();
}

class _EditPlayerState extends State<_EditPlayer> {
  late final VideoPlayerController _c;

  @override
  void initState() {
    super.initState();
    _c = VideoPlayerController.file(File(widget.path))
      ..initialize().then((_) {
        if (mounted) setState(() {});
      });
  }

  @override
  void dispose() {
    _c.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final ready = _c.value.isInitialized;
    return SafeArea(
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Row(children: [
              const Expanded(
                  child: Text('🎬 Your edit', style: TextStyle(fontSize: 15, fontWeight: FontWeight.w700))),
              IconButton(
                  icon: const Icon(Icons.ios_share, size: 20),
                  onPressed: () => Share.shareXFiles(
                      [XFile(widget.path, mimeType: 'video/mp4')],
                      text: 'Edited with Mood AI ✂️')),
              IconButton(icon: const Icon(Icons.close), onPressed: () => Navigator.pop(context)),
            ]),
            const SizedBox(height: 8),
            if (ready)
              GestureDetector(
                onTap: () => setState(() => _c.value.isPlaying ? _c.pause() : _c.play()),
                child: AspectRatio(
                  aspectRatio: _c.value.aspectRatio,
                  child: Stack(alignment: Alignment.bottomCenter, children: [
                    VideoPlayer(_c),
                    VideoProgressIndicator(_c, allowScrubbing: true),
                    if (!_c.value.isPlaying)
                      const Center(child: Icon(Icons.play_arrow, size: 56, color: Colors.white70)),
                  ]),
                ),
              )
            else
              const Padding(padding: EdgeInsets.all(32), child: CircularProgressIndicator()),
          ],
        ),
      ),
    );
  }
}
