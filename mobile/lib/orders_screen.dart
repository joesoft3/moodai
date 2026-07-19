// 🛍 Client Orders (mobile) — manage the magic order links.
//
// Create a link, share it to a WhatsApp client, watch submissions roll in.
// Each client submission appears as a ✋ staged approval in your Plugin Store
// inbox (web /plugins); approving renders + delivers the design, and the
// client downloads it from the same link.
import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:share_plus/share_plus.dart';

import 'api.dart';
import 'main.dart' show MoodColors;

class OrdersScreen extends StatefulWidget {
  const OrdersScreen({super.key});

  @override
  State<OrdersScreen> createState() => _OrdersScreenState();
}

class _OrdersScreenState extends State<OrdersScreen> {
  List<Map<String, dynamic>> _orders = [];
  bool _loading = true;
  bool _busy = false;
  String? _error;
  Timer? _timer;

  @override
  void initState() {
    super.initState();
    _refresh();
    _timer = Timer.periodic(const Duration(seconds: 10), (_) => _refresh(quiet: true));
  }

  @override
  void dispose() {
    _timer?.cancel();
    super.dispose();
  }

  Future<void> _refresh({bool quiet = false}) async {
    try {
      final res = await Api.get('/media/design-orders');
      if (!mounted) return;
      setState(() {
        _orders = ((res['orders'] as List?) ?? []).cast<Map<String, dynamic>>();
        _loading = false;
        if (!quiet) _error = null;
      });
    } catch (e) {
      if (mounted && !quiet) setState(() => _error = '$e');
    }
  }

  String _linkText(String path) =>
      'https://moodai.netlify.app$path'; // web app host (your deployed frontend)

  Future<void> _create() async {
    if (_busy) return;
    setState(() => _busy = true);
    try {
      final res = await Api.post('/media/design-orders', const {});
      final path = '${res['path']}';
      final link = _linkText(path);
      await Clipboard.setData(ClipboardData(text: link));
      await Share.share('🛍 Order your design — tap my Mood AI order link:\n$link',
          subject: 'Design order link');
      _refresh(quiet: true);
    } catch (e) {
      setState(() => _error = '$e');
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _close(Map<String, dynamic> o) async {
    try {
      await Api.post('/media/design-orders/${o['id']}/close', const {});
      _refresh(quiet: true);
    } catch (e) {
      setState(() => _error = '$e');
    }
  }

  Color _statusColor(String s) => switch (s) {
        'delivered' => Colors.greenAccent,
        'staged' => Colors.amberAccent,
        'closed' => Colors.grey,
        _ => MoodColors.accent,
      };

  String _statusLabel(String s) =>
      switch (s) { 'staged' => '✋ waiting your approval', _ => s };

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('🛍 Client Orders')),
      body: RefreshIndicator(
        onRefresh: _refresh,
        child: ListView(
          padding: const EdgeInsets.all(16),
          children: [
            const Text(
              'Share a magic link — your client describes the flyer they want, it lands in your ✋ approvals inbox, you approve, they download from the same link.',
              style: TextStyle(fontSize: 12, color: Colors.grey),
            ),
            const SizedBox(height: 12),
            FilledButton.icon(
              onPressed: _busy ? null : _create,
              icon: _busy
                  ? const SizedBox(width: 16, height: 16, child: CircularProgressIndicator(strokeWidth: 2))
                  : const Icon(Icons.add_link, size: 18),
              label: const Text('New order link (copies + shares)'),
              style: FilledButton.styleFrom(
                backgroundColor: MoodColors.accent,
                foregroundColor: Colors.black,
                padding: const EdgeInsets.symmetric(vertical: 14),
                shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
              ),
            ),
            if (_error != null) ...[
              const SizedBox(height: 8),
              Text(_error!, style: const TextStyle(fontSize: 11, color: Colors.redAccent)),
            ],
            const SizedBox(height: 16),
            if (_loading)
              const Center(child: Padding(padding: EdgeInsets.all(24), child: CircularProgressIndicator()))
            else if (_orders.isEmpty)
              const Padding(
                padding: EdgeInsets.symmetric(vertical: 32),
                child: Center(
                    child: Text('No order links yet — create one above.',
                        style: TextStyle(fontSize: 12, color: Colors.grey))),
              )
            else
              for (final o in _orders)
                Card(
                  color: MoodColors.panel,
                  margin: const EdgeInsets.only(bottom: 8),
                  shape: RoundedRectangleBorder(
                      borderRadius: BorderRadius.circular(12), side: const BorderSide(color: MoodColors.line)),
                  child: Padding(
                    padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
                    child: Row(children: [
                      Container(
                        padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
                        decoration: BoxDecoration(
                          border: Border.all(color: _statusColor('${o['status']}').withValues(alpha: 0.5)),
                          borderRadius: BorderRadius.circular(20),
                        ),
                        child: Text(_statusLabel('${o['status']}'),
                            style: TextStyle(fontSize: 10, color: _statusColor('${o['status']}'))),
                      ),
                      const SizedBox(width: 10),
                      Expanded(
                        child: Text(
                          '${o['customer_name'] != null ? '${o['customer_name']} — ' : ''}${o['kind']}${(o['idea'] as String?)?.isNotEmpty == true ? ' · ${o['idea']}' : ''}',
                          maxLines: 1,
                          overflow: TextOverflow.ellipsis,
                          style: const TextStyle(fontSize: 12, color: Colors.grey),
                        ),
                      ),
                      if (o['status'] != 'closed') ...[
                        IconButton(
                          tooltip: 'Copy + share link',
                          icon: const Icon(Icons.ios_share, size: 18),
                          onPressed: () async {
                            final link = _linkText('${o['path']}');
                            await Clipboard.setData(ClipboardData(text: link));
                            if (context.mounted) {
                              Share.share('🛍 Order your design:\n$link');
                            }
                          },
                        ),
                        IconButton(
                          tooltip: 'Close link',
                          icon: const Icon(Icons.close, size: 18, color: Colors.grey),
                          onPressed: () => _close(o),
                        ),
                      ],
                    ]),
                  ),
                ),
          ],
        ),
      ),
    );
  }
}
