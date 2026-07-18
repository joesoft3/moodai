import 'dart:async';

import 'package:firebase_core/firebase_core.dart';
import 'package:firebase_messaging/firebase_messaging.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter_local_notifications/flutter_local_notifications.dart';

import 'api.dart';

/// 🔔 Push notifications — client half of docs/PUSH-NOTIFICATIONS.md (Phase 2).
/// Everything is defensive: without google-services.google-services.json (or Play services)
/// the app opens and runs exactly as before, just without notifications.
class PushService {
  PushService._();

  static bool _initTried = false;
  static bool _ready = false;
  static bool _tokenSent = false;

  static final FlutterLocalNotificationsPlugin _local = FlutterLocalNotificationsPlugin();

  static const AndroidNotificationChannel _channel = AndroidNotificationChannel(
    'mood_core',
    'Mood AI',
    description: 'Approvals, ⚔️ arena verdicts and workspace alerts',
    importance: Importance.high,
  );

  /// Initialise Firebase + permissions if possible, then register this device
  /// with the backend (idempotent — safe to call after every login/app start).
  static Future<void> registerNow() async {
    if (!_ready) await _ensureInit();
    if (!_ready || _tokenSent) return;
    try {
      final token = await FirebaseMessaging.instance.getToken();
      if (token == null) return;
      await Api.post('/devices', {'token': token, 'platform': _platform()});
      _tokenSent = true;
    } catch (e) {
      if (kDebugMode) debugPrint('push device register failed: $e');
    }
  }

  /// After logout: remove the device mapping again (state resets on next login).
  static Future<void> unregister() async {
    try {
      final token = await FirebaseMessaging.instance.getToken();
      if (token != null) {
        await Api.delete('/devices/${Uri.encodeComponent(token)}');
      }
    } catch (_) {/* never block logout */}
    _tokenSent = false;
  }

  static String _platform() {
    if (kIsWeb) return 'web';
    switch (defaultTargetPlatform) {
      case TargetPlatform.iOS:
        return 'ios';
      case TargetPlatform.android:
        return 'android';
      default:
        return 'android';
    }
  }

  static Future<void> _ensureInit() async {
    if (_initTried) return;
    _initTried = true;
    try {
      await Firebase.initializeApp();

      const initSettings = InitializationSettings(
        android: AndroidInitializationSettings('@mipmap/ic_launcher'),
      );
      await _local.initialize(initSettings);
      await _local
          .resolvePlatformSpecificImplementation<AndroidFlutterLocalNotificationsPlugin>()
          ?.createNotificationChannel(_channel);

      final messaging = FirebaseMessaging.instance;
      final perm = await messaging.requestPermission();
      if (perm.authorizationStatus == AuthorizationStatus.denied) {
        return; // user said no — everything still works, just silently
      }
      _ready = true;

      messaging.onTokenRefresh.listen((t) {
        _tokenSent = false;
        unawaited(registerNow());
      });
      FirebaseMessaging.onMessage.listen(_showLocalWhenForeground);
    } catch (e) {
      if (kDebugMode) debugPrint('push disabled (init): $e');
    }
  }

  /// Foreground messages have no OS tray entry — paint one locally.
  static Future<void> _showLocalWhenForeground(RemoteMessage message) async {
    final n = message.notification;
    final title = n?.title ?? 'Mood AI';
    final body = n?.body ?? '';
    if (body.isEmpty) return;
    try {
      await _local.show(
        message.hashCode,
        title,
        body,
        NotificationDetails(
          android: AndroidNotificationDetails(
            _channel.id,
            _channel.name,
            channelDescription: _channel.description,
            importance: Importance.high,
            priority: Priority.high,
            icon: '@mipmap/ic_launcher',
          ),
        ),
      );
    } catch (e) {
      if (kDebugMode) debugPrint('local notification failed: $e');
    }
  }
}
