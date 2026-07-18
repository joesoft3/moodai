import 'dart:async';

import 'package:flutter/material.dart';

import 'api.dart';
import 'chat_screen.dart';
import 'login_screen.dart';
import 'push.dart';

void main() => runApp(const MoodApp());

class MoodColors {
  static const base = Color(0xFF0B0F14);
  static const panel = Color(0xFF12181F);
  static const line = Color(0xFF1E293B);
  static const accent = Color(0xFF7C9BFF);
}

class MoodApp extends StatelessWidget {
  const MoodApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'Mood AI',
      debugShowCheckedModeBanner: false,
      theme: ThemeData(
        brightness: Brightness.dark,
        scaffoldBackgroundColor: MoodColors.base,
        colorScheme: const ColorScheme.dark(
          primary: MoodColors.accent,
          surface: MoodColors.panel,
          outline: MoodColors.line,
        ),
        appBarTheme: const AppBarTheme(backgroundColor: MoodColors.panel, elevation: 0),
        inputDecorationTheme: InputDecorationTheme(
          filled: true,
          fillColor: MoodColors.panel,
          border: OutlineInputBorder(
            borderRadius: BorderRadius.circular(14),
            borderSide: const BorderSide(color: MoodColors.line),
          ),
          enabledBorder: OutlineInputBorder(
            borderRadius: BorderRadius.circular(14),
            borderSide: const BorderSide(color: MoodColors.line),
          ),
          contentPadding: const EdgeInsets.symmetric(horizontal: 16, vertical: 14),
        ),
        useMaterial3: true,
      ),
      home: const _Gate(),
    );
  }
}

/// Decides between login and chat depending on a stored token.
class _Gate extends StatelessWidget {
  const _Gate();

  @override
  Widget build(BuildContext context) {
    return FutureBuilder<String?>(
      future: Api.getToken(),
      builder: (context, snap) {
        if (snap.connectionState != ConnectionState.done) {
          return const Scaffold(body: Center(child: CircularProgressIndicator()));
        }
        if (snap.data != null) {
          unawaited(PushService.registerNow()); // 🔔 re-register device on cold start
        }
        return snap.data == null ? const LoginScreen() : const ChatScreen();
      },
    );
  }
}
