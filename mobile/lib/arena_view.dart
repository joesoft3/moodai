import 'package:flutter/material.dart';

import 'main.dart' show MoodColors;

/// ⚔️ Multi-model arena — live progress + full verdict panel (web parity).
///
/// Live wire events from /agents/arena/stream:
///   topic → warning* → draft_start×N → draft_delta* → draft_done×N →
///   vote_cast×N → arena_verdict → (winning draft streams as deltas)
/// Persisted arena answers restore from the assistant message `meta`
/// (mode == 'arena') with the same verdict fields.

/// Live state accumulated while the arena streams.
class ArenaLiveState {
  ArenaLiveState({this.topic, this.brand, this.rematch = false});

  String? topic;
  String? brand;
  bool rematch;
  final List<String> warnings = [];
  final List<ArenaDraftProgress> drafts = []; // in panel order
  final List<ArenaBallot> votes = [];

  void startDraft(String provider) {
    if (drafts.any((d) => d.provider == provider)) return;
    drafts.add(ArenaDraftProgress(provider));
  }

  void addDelta(String provider, int chars) {
    startDraft(provider);
    drafts.firstWhere((d) => d.provider == provider).chars += chars;
  }

  void finishDraft(String provider) {
    startDraft(provider);
    drafts.firstWhere((d) => d.provider == provider).done = true;
  }
}

class ArenaDraftProgress {
  ArenaDraftProgress(this.provider);
  final String provider;
  int chars = 0;
  bool done = false;
}

class ArenaBallot {
  ArenaBallot({required this.provider, this.vote, this.rationale = '', this.invalid = false});
  final String provider;
  final String? vote;
  final String rationale;
  final bool invalid;
}

class ArenaDraft {
  ArenaDraft({required this.provider, required this.content, this.slot});
  final String provider;
  final String content;
  final String? slot; // anonymized letter (A/B/C…) assigned by draft_order
}

/// Final verdict — from a live `arena_verdict` event or persisted message meta.
class ArenaVerdict {
  ArenaVerdict({
    required this.winner,
    required this.drafts,
    required this.draftOrder,
    required this.votes,
    this.scores = const {},
    this.usage = const {},
    this.judge = 'Grok-4',
    this.brand,
  });

  final String winner;
  final List<ArenaDraft> drafts; // index i ↔ draftOrder[i]
  final List<String> draftOrder;
  final List<ArenaBallot> votes;
  final Map<String, Map<String, int>> scores; // slot → {accuracy, clarity} 1–10
  final Map<String, Map<String, int>> usage; // provider → {in, out}
  final String judge;
  final String? brand;

  int get validBallots => votes.where((v) => !v.invalid && v.vote != null).length;

  static Map<String, Map<String, int>> _intMap2(dynamic raw) {
    final out = <String, Map<String, int>>{};
    if (raw is Map) {
      raw.forEach((k, v) {
        if (v is Map) {
          out['$k'] = {
            for (final e in v.entries) '${e.key}': (e.value is num) ? (e.value as num).toInt() : 0,
          };
        }
      });
    }
    return out;
  }

  factory ArenaVerdict.fromEvent(Map ev) => ArenaVerdict(
        winner: '${ev['winner'] ?? '?'}',
        judge: '${ev['judge'] ?? 'Grok-4'}',
        brand: ev['brand'] as String?,
        draftOrder: [for (final l in (ev['draft_order'] as List? ?? [])) '$l'],
        drafts: [
          for (final d in (ev['drafts'] as List? ?? []))
            ArenaDraft(
              provider: '${d['provider'] ?? '?'}',
              content: '${d['content'] ?? ''}',
              slot: d['slot'] as String?,
            ),
        ],
        votes: [
          for (final v in (ev['votes'] as List? ?? []))
            ArenaBallot(
              provider: '${v['provider'] ?? '?'}',
              vote: (v['ballot'] is Map) ? '${(v['ballot'] as Map)['vote']}' : null,
              rationale: (v['ballot'] is Map) ? '${(v['ballot'] as Map)['rationale'] ?? ''}' : '',
              invalid: v['valid'] != true,
            ),
        ],
        scores: _intMap2(ev['scores']),
        usage: _intMap2(ev['usage']),
      );

  /// Reload path: backend persists verdict fields onto the message `meta`.
  factory ArenaVerdict.fromMeta(Map meta) => ArenaVerdict.fromEvent(meta);
}

String arenaProviderIcon(String p) {
  final k = p.toLowerCase();
  if (k.contains('grok-code')) return '💻';
  if (k.contains('gemini-2.5-flash')) return '⚡';
  if (k.contains('grok')) return '✦';
  if (k.contains('gpt')) return '🟢';
  if (k.contains('gemini')) return '🔷';
  return '🤖';
}

/// The panel shown above arena answers: live progress first, verdict after.
class ArenaPanel extends StatelessWidget {
  const ArenaPanel({super.key, this.live, this.verdict, this.onRematch});

  final ArenaLiveState? live;
  final ArenaVerdict? verdict;
  final VoidCallback? onRematch;

  @override
  Widget build(BuildContext context) {
    final v = verdict;
    final l = live;
    final brand = v?.brand ?? l?.brand;
    return Container(
      margin: const EdgeInsets.only(bottom: 8),
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: MoodColors.accent.withOpacity(0.06),
        borderRadius: BorderRadius.circular(14),
        border: Border.all(color: MoodColors.accent.withOpacity(0.25)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            brand != null ? '⚔️ $brand · multi-model arena' : '⚔️ Multi-model arena',
            style: const TextStyle(fontSize: 12, fontWeight: FontWeight.w700, color: MoodColors.accent),
          ),
          if (l?.topic != null) ...[
            const SizedBox(height: 4),
            Text(
              '${l!.rematch ? '🔁 REMATCH — beat the previous winner · ' : ''}“${l.topic}”',
              style: const TextStyle(fontSize: 11, color: Colors.grey, fontStyle: FontStyle.italic),
            ),
          ],
          if (v == null && l != null) ..._liveLines(l),
          if (l != null)
            for (final w in l.warnings)
              Padding(
                padding: const EdgeInsets.only(top: 4),
                child: Text('⚠️ $w', style: const TextStyle(fontSize: 11, color: Colors.amber)),
              ),
          if (v != null) ..._verdict(context, v),
        ],
      ),
    );
  }

  List<Widget> _liveLines(ArenaLiveState l) => [
        const SizedBox(height: 8),
        for (final d in l.drafts)
          Padding(
            padding: const EdgeInsets.only(bottom: 2),
            child: Text(
              '${d.done ? '✅' : '⏳'} ${arenaProviderIcon(d.provider)} ${d.provider} '
              '${d.done ? 'drafted' : d.chars > 0 ? 'drafting… ${d.chars} chars' : 'drafting…'}',
              style: const TextStyle(fontSize: 11, color: Colors.grey),
            ),
          ),
        for (final b in l.votes)
          Padding(
            padding: const EdgeInsets.only(bottom: 2),
            child: Text(
              '${b.invalid ? '⚠️' : '🗳️'} ${arenaProviderIcon(b.provider)} ${b.provider} voted'
              '${b.invalid ? ' (invalid ballot)' : ' for ${b.vote}'}',
              style: const TextStyle(fontSize: 11, color: Colors.grey),
            ),
          ),
        if (l.drafts.isEmpty)
          const Padding(
            padding: EdgeInsets.only(top: 6),
            child: Row(children: [
              SizedBox(width: 14, height: 14, child: CircularProgressIndicator(strokeWidth: 2)),
              SizedBox(width: 8),
              Text('assembling the panel…', style: TextStyle(fontSize: 11, color: Colors.grey)),
            ]),
          ),
      ];

  List<Widget> _verdict(BuildContext context, ArenaVerdict v) => [
        const SizedBox(height: 8),
        Container(
          width: double.infinity,
          padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 8),
          decoration: BoxDecoration(
            color: MoodColors.accent.withOpacity(0.12),
            borderRadius: BorderRadius.circular(10),
            border: Border.all(color: MoodColors.accent.withOpacity(0.3)),
          ),
          child: Text(
            '👑 ${v.judge} verdict: ${v.winner} · ${v.validBallots}/${v.votes.length} valid ballots',
            style: const TextStyle(fontSize: 12, fontWeight: FontWeight.w700, color: MoodColors.accent),
          ),
        ),
        const SizedBox(height: 8),
        for (var i = 0; i < v.drafts.length; i++) _draftCard(context, v, i),
        if (v.votes.isNotEmpty) ...[
          const SizedBox(height: 6),
          Text('🗳️ ballots', style: TextStyle(fontSize: 10, color: Colors.grey.shade600, fontWeight: FontWeight.w600)),
          for (final b in v.votes)
            Padding(
              padding: const EdgeInsets.only(top: 2),
              child: Text(
                '${b.invalid ? '⚠️' : '🗳️'} ${arenaProviderIcon(b.provider)} ${b.provider} → '
                '${b.invalid ? 'invalid ballot' : b.vote}${b.rationale.isNotEmpty ? ' — ${b.rationale}' : ''}',
                style: const TextStyle(fontSize: 11, color: Colors.grey),
              ),
            ),
        ],
        if (v.usage.isNotEmpty) ...[
          const SizedBox(height: 8),
          Wrap(
            spacing: 6,
            runSpacing: 4,
            children: [
              for (final e in v.usage.entries)
                Container(
                  padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
                  decoration: BoxDecoration(
                    borderRadius: BorderRadius.circular(999),
                    border: Border.all(color: MoodColors.line),
                  ),
                  child: Text(
                    '${e.key}: ${e.value['in'] ?? 0}→${e.value['out'] ?? 0} tok',
                    style: TextStyle(fontSize: 10, color: Colors.grey.shade600),
                  ),
                ),
            ],
          ),
        ],
        if (onRematch != null) ...[
          const SizedBox(height: 8),
          Align(
            alignment: Alignment.centerRight,
            child: OutlinedButton.icon(
              onPressed: onRematch,
              icon: const Text('🔁', style: TextStyle(fontSize: 12)),
              label: const Text('Rematch', style: TextStyle(fontSize: 12)),
              style: OutlinedButton.styleFrom(
                foregroundColor: MoodColors.accent,
                side: BorderSide(color: MoodColors.accent.withOpacity(0.4)),
                padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
                minimumSize: Size.zero,
                tapTargetSize: MaterialTapTargetSize.shrinkWrap,
              ),
            ),
          ),
        ],
      ];

  Widget _draftCard(BuildContext context, ArenaVerdict v, int i) {
    final d = v.drafts[i];
    final slot = i < v.draftOrder.length ? v.draftOrder[i] : d.slot;
    final sc = slot != null ? v.scores[slot] : null;
    final isWinner = d.provider == v.winner;
    return Container(
      margin: const EdgeInsets.only(bottom: 6),
      decoration: BoxDecoration(
        color: Colors.white.withOpacity(0.03),
        borderRadius: BorderRadius.circular(10),
        border: Border.all(color: isWinner ? MoodColors.accent.withOpacity(0.45) : MoodColors.line),
      ),
      child: Theme(
        data: Theme.of(context).copyWith(dividerColor: Colors.transparent),
        child: ExpansionTile(
          dense: true,
          tilePadding: const EdgeInsets.symmetric(horizontal: 10),
          childrenPadding: const EdgeInsets.fromLTRB(10, 0, 10, 10),
          title: Row(
            children: [
              Text(slot != null ? '$slot · ' : '', style: TextStyle(fontSize: 11, color: Colors.grey.shade600)),
              Expanded(
                child: Text(
                  '${arenaProviderIcon(d.provider)} ${d.provider}${isWinner ? ' 👑' : ''}',
                  style: TextStyle(
                    fontSize: 12,
                    fontWeight: FontWeight.w600,
                    color: isWinner ? MoodColors.accent : Colors.grey.shade300,
                  ),
                  overflow: TextOverflow.ellipsis,
                ),
              ),
              if (sc != null) ...[
                _scoreChip('🎯 ${sc['accuracy'] ?? 0}'),
                const SizedBox(width: 4),
                _scoreChip('✍️ ${sc['clarity'] ?? 0}'),
              ],
            ],
          ),
          subtitle: Text(
            d.content.length > 90 ? '${d.content.substring(0, 90)}…' : d.content,
            maxLines: 1,
            overflow: TextOverflow.ellipsis,
            style: TextStyle(fontSize: 11, color: Colors.grey.shade600),
          ),
          children: [
            Align(
              alignment: Alignment.centerLeft,
              child: SelectableText(d.content, style: const TextStyle(fontSize: 12, height: 1.4)),
            ),
          ],
        ),
      ),
    );
  }

  Widget _scoreChip(String label) => Container(
        padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
        decoration: BoxDecoration(
          color: MoodColors.accent.withOpacity(0.1),
          borderRadius: BorderRadius.circular(999),
          border: Border.all(color: MoodColors.accent.withOpacity(0.25)),
        ),
        child: Text(label, style: const TextStyle(fontSize: 10, color: MoodColors.accent)),
      );
}
