import 'dart:async';
import 'dart:convert';

import 'package:http/http.dart' as http;
import 'package:shared_preferences/shared_preferences.dart';

/// Thin client for the Mood AI API (FastAPI, /api/v1).
/// Pass the API root at build/run time:
///   flutter run --dart-define=API_URL=http://192.168.1.10:8000/api/v1
/// Default targets the Android emulator's host loopback.
class Api {
  static const String baseUrl =
      String.fromEnvironment('API_URL', defaultValue: 'http://10.0.2.2:8000/api/v1');

  static const _tokenKey = 'mood_token';
  static final http.Client _client = http.Client();

  // ------------------------------------------------------------------ auth
  static Future<String?> getToken() async =>
      (await SharedPreferences.getInstance()).getString(_tokenKey);

  static Future<void> setToken(String? token) async {
    final prefs = await SharedPreferences.getInstance();
    if (token == null) {
      await prefs.remove(_tokenKey);
    } else {
      await prefs.setString(_tokenKey, token);
    }
  }

  static Map<String, String> _headers(String? token) => {
        'Content-Type': 'application/json',
        if (token != null) 'Authorization': 'Bearer $token',
      };

  static String _error(http.Response res) {
    try {
      final body = jsonDecode(res.body);
      final detail = body is Map ? body['detail'] : null;
      if (detail is String) return detail;
      return jsonEncode(body);
    } catch (_) {
      return 'HTTP ${res.statusCode}';
    }
  }

  // -------------------------------------------------------------- REST calls
  static Future<Map<String, dynamic>> post(String path, Map<String, dynamic> body) async {
    final token = await getToken();
    final res = await _client
        .post(Uri.parse('$baseUrl$path'), headers: _headers(token), body: jsonEncode(body))
        .timeout(const Duration(seconds: 30));
    if (res.statusCode >= 400) throw Exception(_error(res));
    return jsonDecode(res.body) as Map<String, dynamic>;
  }

  static Future<dynamic> get(String path) async {
    final token = await getToken();
    final res = await _client
        .get(Uri.parse('$baseUrl$path'), headers: _headers(token))
        .timeout(const Duration(seconds: 30));
    if (res.statusCode >= 400) throw Exception(_error(res));
    return jsonDecode(res.body);
  }

  static Future<void> delete(String path) async {
    final token = await getToken();
    final res = await _client
        .delete(Uri.parse('$baseUrl$path'), headers: _headers(token))
        .timeout(const Duration(seconds: 30));
    if (res.statusCode >= 400) throw Exception(_error(res));
  }

  // ------------------------------------------------------ multipart (voice/files)
  static Future<Map<String, dynamic>> postMultipart(
    String path,
    List<int> bytes,
    String filename, {
    String field = 'file',
    Map<String, String> fields = const {},
  }) async {
    final token = await getToken();
    final req = http.MultipartRequest('POST', Uri.parse('$baseUrl$path'));
    if (token != null) req.headers['Authorization'] = 'Bearer $token';
    req.fields.addAll(fields);
    req.files.add(http.MultipartFile.fromBytes(field, bytes, filename: filename));
    final streamed = await _client.send(req).timeout(const Duration(minutes: 3));
    final res = await http.Response.fromStream(streamed);
    if (res.statusCode >= 400) throw Exception(_error(res));
    final body = jsonDecode(res.body);
    return body is Map<String, dynamic> ? body : <String, dynamic>{};
  }

  // ------------------------------------------------------- audio file analysis
  /// Upload an audio/music file for transcription + AI analysis (lyrics, mood,
  /// "what song is this?"). Returns transcript, analysis and conversation_id.
  static Future<Map<String, dynamic>> analyzeAudio(
    List<int> bytes,
    String filename, {
    String? prompt,
    String? conversationId,
  }) =>
      postMultipart('/files/analyze-audio', bytes, filename, fields: {
        if (prompt != null && prompt.isNotEmpty) 'prompt': prompt,
        if (conversationId != null) 'conversation_id': conversationId,
      });

  // ------------------------------------------------------- SSE streaming chat
  /// Yields decoded SSE event objects from a streaming endpoint
  /// (/chat/stream, /agents/stream, /deepsearch/stream).
  static Stream<Map<String, dynamic>> streamTo(String endpoint, Map<String, dynamic> payload) async* {
    final token = await getToken();
    final req = http.Request('POST', Uri.parse('$baseUrl$endpoint'));
    req.headers.addAll(_headers(token));
    req.body = jsonEncode(payload);
    final res = await _client.send(req).timeout(const Duration(minutes: 6));
    if (res.statusCode >= 400) {
      final body = await res.stream.bytesToString();
      final decoded = http.Response(body, res.statusCode);
      throw Exception(_error(decoded));
    }
    var buf = '';
    await for (final chunk in res.stream.transform(utf8.decoder)) {
      buf += chunk;
      while (buf.contains('\n\n')) {
        final i = buf.indexOf('\n\n');
        final raw = buf.substring(0, i).trim();
        buf = buf.substring(i + 2);
        if (!raw.startsWith('data:')) continue;
        final line = raw.substring(5).trim();
        if (line.isEmpty) continue;
        try {
          yield jsonDecode(line) as Map<String, dynamic>;
        } catch (_) {
          /* malformed event — skip */
        }
      }
    }
  }

  /// Back-compat helper for the standard chat stream.
  static Stream<Map<String, dynamic>> streamChat({
    String? conversationId,
    required String message,
    List<String> files = const [],
    bool search = true,
  }) =>
      streamTo('/chat/stream', {
        'conversation_id': conversationId,
        'message': message,
        'files': files,
        'search': search,
      });
}
