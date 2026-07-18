// 🎨 Design Studio (mobile) — flyers, logos & banners at print resolution.
//
// Mirrors the web /design studio: kind tabs, art-director brief, style/palette
// chips, brand-aware generation, two-tier PNG downloads (web / 300-DPI print),
// shard gallery, share/save (WhatsApp share sheet) and delete.
import 'dart:async';
import 'dart:io';
import 'dart:typed_data';

import 'package:flutter/material.dart';
import 'package:path_provider/path_provider.dart';
import 'package:share_plus/share_plus.dart';

import 'api.dart';
import 'main.dart' show MoodColors;

class DesignScreen extends StatefulWidget {
  const DesignScreen({super.key});

  @override
  State<DesignScreen> createState() => _DesignScreenState();
}

class _DesignScreenState extends State<DesignScreen> {
  // ---- catalog (mirrors backend designer.py presets) ----
  static const _kinds = <String, Map<String, Object>>{
    'flyer': {'label': 'Flyer', 'icon': Icons.crop_portrait, 'print': '2048×3072'},
    'logo': {'label': 'Logo', 'icon': Icons.brush_outlined, 'print': '2048×2048'},
    'banner': {'label': 'Banner', 'icon': Icons.crop_16_9, 'print': '3072×2048'},
  };
  static const _styles = ['minimal', 'bold', 'luxury', 'playful', 'corporate', 'retro', 'neon'];
  static const _palettes = <String, List<Color>>{
    'auto': [Colors.grey, Colors.white],
    'noir': [Color(0xFF111111), Colors.white],
    'sunset': [Color(0xFFFF7E5F), Color(0xFFD23B8F)],
    'ocean': [Color(0xFF0F4C81), Color(0xFF3AA99E)],
    'forest': [Color(0xFF1D4D2B), Color(0xFFE8DCC0)],
    'gold': [Color(0xFF0A0A0A), Color(0xFFD4AF37)],
    'candy': [Color(0xFFFFB3D9), Color(0xFFD9B3FF)],
  };

  String _kind = 'flyer';
  String _style = 'minimal';
  String _palette = 'auto';
  bool _transparent = false;
  bool _enhance = true;
  bool _useBrand = false;
  bool _busy = false;
  final _idea = TextEditingController();
  String? _toast;

  List<dynamic> _designs = [];
  final Map<String, Uint8List> _bytes = {}; // id → web-tier png

  @override
  void initState() {
    super.initState();
    _refresh();
  }

  void _flash(String msg) {
    if (!mounted) return;
    setState(() => _toast = msg);
    Timer(const Duration(seconds: 4), () {
      if (mounted) setState(() => _toast = null);
    });
  }

  Future<void> _refresh() async {
    try {
      final res = await Api.get('/media/designs');
      final list = (res['designs'] as List?) ?? [];
      if (!mounted) return;
      setState(() => _designs = list);
      for (final d in list) {
        final id = '${d['id']}';
        if (!_bytes.containsKey(id)) {
          Api.getBytes('/media/designs/$id/download?tier=web').then((b) {
            if (mounted) setState(() => _bytes[id] = b);
          }).catchError((_) {});
        }
      }
    } catch (e) {
      _flash('$e');
    }
  }

  Future<void> _generate() async {
    if (_busy || _idea.text.trim().length < 3) return;
    setState(() => _busy = true);
    try {
      final d = await Api.post('/media/designs', {
        'idea': _idea.text.trim(),
        'kind': _kind,
        'style': _style,
        'palette': _palette,
        'transparent': _kind == 'logo' && _transparent,
        'enhance': _enhance,
        'use_brand': _useBrand,
      }, timeout: const Duration(seconds: 150));
      setState(() => _designs = [d, ..._designs]);
      final id = '${d['id']}';
      Api.getBytes('/media/designs/$id/download?tier=web').then((b) {
        if (mounted) setState(() => _bytes[id] = b);
      }).catchError((_) {});
      _flash('✨ Design ready — Print HD for crisp output!');
    } catch (e) {
      _flash('$e');
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<String> _saveTemp(Uint8List bytes, String name) async {
    final dir = await getTemporaryDirectory();
    final f = File('${dir.path}/$name');
    await f.writeAsBytes(bytes);
    return f.path;
  }

  Future<void> _share(Map<String, dynamic> d, String tier) async {
    final id = '${d['id']}';
    try {
      final bytes = await Api.getBytes('/media/designs/$id/download?tier=$tier');
      final path = await _saveTemp(bytes, 'mood-${d['kind']}-${id.substring(0, 8)}-$tier.png');
      await Share.shareXFiles(
        [XFile(path, mimeType: 'image/png')],
        text: 'Made with Mood AI Design Studio 🎨',
      );
    } catch (e) {
      _flash('$e');
    }
  }

  Future<void> _delete(String id) async {
    try {
      await Api.delete('/media/designs/$id');
      setState(() {
        _designs = _designs.where((d) => '${d['id']}' != id).toList();
        _bytes.remove(id);
      });
    } catch (e) {
      _flash('$e');
    }
  }

  Widget _chip(String label, bool active, VoidCallback onTap, {List<Color>? swatch}) {
    return GestureDetector(
      onTap: onTap,
      child: Container(
        margin: const EdgeInsets.only(right: 8, bottom: 8),
        padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
        decoration: BoxDecoration(
          color: active ? MoodColors.accent.withValues(alpha: 0.15) : Colors.white.withValues(alpha: 0.05),
          border: Border.all(color: active ? MoodColors.accent : MoodColors.line),
          borderRadius: BorderRadius.circular(20),
        ),
        child: Row(mainAxisSize: MainAxisSize.min, children: [
          if (swatch != null)
            Container(
              width: 12, height: 12,
              margin: const EdgeInsets.only(right: 6),
              decoration: BoxDecoration(
                gradient: LinearGradient(colors: swatch),
                shape: BoxShape.circle,
                border: Border.all(color: Colors.white24),
              ),
            ),
          Text(label, style: TextStyle(fontSize: 12, color: active ? MoodColors.accent : Colors.white70)),
        ]),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('🎨 Design Studio')),
      body: SafeArea(
        child: SingleChildScrollView(
          padding: const EdgeInsets.all(14),
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            // kind tabs
            Row(children: _kinds.entries.map((e) {
              final active = _kind == e.key;
              return Expanded(
                child: GestureDetector(
                  onTap: () => setState(() => _kind = e.key),
                  child: Container(
                    margin: const EdgeInsets.symmetric(horizontal: 3),
                    padding: const EdgeInsets.all(10),
                    decoration: BoxDecoration(
                      color: active ? MoodColors.accent.withValues(alpha: 0.12) : MoodColors.panel,
                      border: Border.all(color: active ? MoodColors.accent : MoodColors.line),
                      borderRadius: BorderRadius.circular(12),
                    ),
                    child: Column(children: [
                      Icon(e.value['icon'] as IconData, size: 18,
                          color: active ? MoodColors.accent : Colors.white54),
                      const SizedBox(height: 4),
                      Text('${e.value['label']}',
                          style: TextStyle(
                              fontSize: 12,
                              fontWeight: FontWeight.w600,
                              color: active ? MoodColors.accent : Colors.white)),
                      Text('${e.value['print']}', style: const TextStyle(fontSize: 9, color: Colors.white38)),
                    ]),
                  ),
                ),
              );
            }).toList()),
            const SizedBox(height: 12),

            // idea
            TextField(
              controller: _idea,
              maxLines: 3,
              maxLength: 1500,
              style: const TextStyle(fontSize: 13),
              decoration: InputDecoration(
                counterText: '',
                hintText: _kind == 'logo'
                    ? "e.g. Minimal bird mark for 'Akwaaba Coffee' — geometric bird over wordmark"
                    : "e.g. Waakye Friday at Auntie's Spot — from GH¢20, 11am sharp, East Legon junction",
                hintStyle: const TextStyle(fontSize: 12, color: Colors.white38),
                filled: true,
                fillColor: Colors.white.withValues(alpha: 0.05),
                border: OutlineInputBorder(
                  borderRadius: BorderRadius.circular(12),
                  borderSide: const BorderSide(color: MoodColors.line),
                ),
                enabledBorder: OutlineInputBorder(
                  borderRadius: BorderRadius.circular(12),
                  borderSide: const BorderSide(color: MoodColors.line),
                ),
                focusedBorder: OutlineInputBorder(
                  borderRadius: BorderRadius.circular(12),
                  borderSide: const BorderSide(color: MoodColors.accent),
                ),
              ),
            ),
            const Text("💡 Exact text in 'quotes' keeps its spelling.",
                style: TextStyle(fontSize: 10, color: Colors.white38)),
            const SizedBox(height: 12),

            const Text('Style', style: TextStyle(fontSize: 11, color: Colors.white54, letterSpacing: 1)),
            const SizedBox(height: 6),
            Wrap(children: _styles.map((s) => _chip(s, _style == s, () => setState(() => _style = s))).toList()),
            const Text('Palette', style: TextStyle(fontSize: 11, color: Colors.white54, letterSpacing: 1)),
            const SizedBox(height: 6),
            Wrap(children: _palettes.entries
                .map((p) => _chip(p.key, _palette == p.key, () => setState(() => _palette = p.key), swatch: p.value))
                .toList()),

            Wrap(spacing: 16, children: [
              Row(mainAxisSize: MainAxisSize.min, children: [
                Checkbox(value: _enhance, activeColor: MoodColors.accent,
                    onChanged: (v) => setState(() => _enhance = v ?? true)),
                const Text('Art-director brief', style: TextStyle(fontSize: 12)),
              ]),
              if (_kind == 'logo')
                Row(mainAxisSize: MainAxisSize.min, children: [
                  Checkbox(value: _transparent, activeColor: MoodColors.accent,
                      onChanged: (v) => setState(() => _transparent = v ?? false)),
                  const Text('Transparent bg', style: TextStyle(fontSize: 12)),
                ]),
              if (_kind != 'logo')
                Row(mainAxisSize: MainAxisSize.min, children: [
                  Checkbox(value: _useBrand, activeColor: MoodColors.accent,
                      onChanged: (v) => setState(() => _useBrand = v ?? false)),
                  const Text('Use my brand', style: TextStyle(fontSize: 12)),
                ]),
            ]),
            const SizedBox(height: 4),

            SizedBox(
              width: double.infinity,
              child: ElevatedButton.icon(
                onPressed: _busy ? null : _generate,
                icon: _busy
                    ? const SizedBox(width: 16, height: 16, child: CircularProgressIndicator(strokeWidth: 2))
                    : const Icon(Icons.auto_awesome, size: 18),
                label: Text(_busy ? 'Designing…' : 'Generate design'),
                style: ElevatedButton.styleFrom(
                  backgroundColor: MoodColors.accent,
                  foregroundColor: Colors.black,
                  padding: const EdgeInsets.symmetric(vertical: 14),
                  shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
                ),
              ),
            ),
            if (_busy)
              const Padding(
                padding: EdgeInsets.only(top: 8),
                child: Text('Art-directing → rendering → 300-DPI print pass…',
                    style: TextStyle(fontSize: 11, color: Colors.white38)),
              ),
            if (_toast != null)
              Container(
                margin: const EdgeInsets.only(top: 10),
                padding: const EdgeInsets.all(10),
                decoration: BoxDecoration(
                  color: MoodColors.accent.withValues(alpha: 0.12),
                  border: Border.all(color: MoodColors.accent.withValues(alpha: 0.4)),
                  borderRadius: BorderRadius.circular(10),
                ),
                child: Text(_toast!, style: const TextStyle(fontSize: 12, color: MoodColors.accent)),
              ),
            const SizedBox(height: 18),

            Text('My designs (${_designs.length})',
                style: const TextStyle(fontSize: 14, fontWeight: FontWeight.w600)),
            const SizedBox(height: 10),
            if (_designs.isEmpty)
              Container(
                width: double.infinity,
                padding: const EdgeInsets.all(28),
                decoration: BoxDecoration(
                  border: Border.all(color: MoodColors.line),
                  borderRadius: BorderRadius.circular(12),
                ),
                child: const Column(children: [
                  Icon(Icons.image_outlined, color: Colors.white24, size: 30),
                  SizedBox(height: 8),
                  Text('No designs yet — describe one above ✨',
                      style: TextStyle(fontSize: 12, color: Colors.white38)),
                ]),
              )
            else
              GridView.builder(
                shrinkWrap: true,
                physics: const NeverScrollableScrollPhysics(),
                gridDelegate: const SliverGridDelegateWithFixedCrossAxisCount(
                    crossAxisCount: 2, mainAxisSpacing: 10, crossAxisSpacing: 10, childAspectRatio: 0.78),
                itemCount: _designs.length,
                itemBuilder: (_, i) {
                  final d = _designs[i] as Map<String, dynamic>;
                  final id = '${d['id']}';
                  final bytes = _bytes[id];
                  return Container(
                    decoration: BoxDecoration(
                      color: Colors.white.withValues(alpha: 0.05),
                      border: Border.all(color: MoodColors.line),
                      borderRadius: BorderRadius.circular(12),
                    ),
                    clipBehavior: Clip.antiAlias,
                    child: Column(children: [
                      Expanded(
                        child: Stack(fit: StackFit.expand, children: [
                          Container(
                            color: const Color(0xFF151B26),
                            alignment: Alignment.center,
                            child: bytes != null
                                ? Image.memory(bytes, fit: BoxFit.contain)
                                : const CircularProgressIndicator(strokeWidth: 2),
                          ),
                          Positioned(
                            left: 6, top: 6,
                            child: Container(
                              padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
                              decoration: BoxDecoration(
                                color: Colors.black54, borderRadius: BorderRadius.circular(10)),
                              child: Text('${d['kind']}',
                                  style: const TextStyle(fontSize: 9, color: Colors.white)),
                            ),
                          ),
                        ]),
                      ),
                      Padding(
                        padding: const EdgeInsets.all(6),
                        child: Row(mainAxisAlignment: MainAxisAlignment.spaceEvenly, children: [
                          _pill('Share', Icons.share_outlined, () => _share(d, 'web'), accent: true),
                          _pill('Print', Icons.download_outlined, () => _share(d, 'print')),
                          _pill('Del', Icons.delete_outline, () => _delete(id)),
                        ]),
                      ),
                    ]),
                  );
                },
              ),
          ]),
        ),
      ),
    );
  }

  Widget _pill(String label, IconData icon, VoidCallback onTap, {bool accent = false}) {
    return GestureDetector(
      onTap: onTap,
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 9, vertical: 6),
        decoration: BoxDecoration(
          color: accent ? MoodColors.accent.withValues(alpha: 0.15) : Colors.transparent,
          border: Border.all(color: accent ? MoodColors.accent.withValues(alpha: 0.5) : MoodColors.line),
          borderRadius: BorderRadius.circular(8),
        ),
        child: Row(children: [
          Icon(icon, size: 11, color: accent ? MoodColors.accent : Colors.white60),
          const SizedBox(width: 3),
          Text(label, style: TextStyle(fontSize: 9, color: accent ? MoodColors.accent : Colors.white60)),
        ]),
      ),
    );
  }
}
