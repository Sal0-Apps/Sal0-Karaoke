package com.sal0.karaoke;

import android.content.Context;
import android.content.SharedPreferences;

import java.net.URI;
import java.net.URISyntaxException;
import java.util.Locale;

final class ServerConfig {
    private static final String PREFS = "sal0_server";
    private static final String KEY_WIFI = "wifi_ssid";
    private static final String KEY_LOCAL = "local_url";
    private static final String KEY_EXTERNAL = "external_url";

    final String wifiSsid;
    final String localUrl;
    final String externalUrl;

    ServerConfig(String wifiSsid, String localUrl, String externalUrl) {
        this.wifiSsid = ConnectionRouter.normalizeSsid(wifiSsid);
        this.localUrl = normalizeBaseUrl(localUrl);
        this.externalUrl = normalizeBaseUrl(externalUrl);
    }

    static ServerConfig load(Context context) {
        SharedPreferences preferences = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE);
        if (!preferences.contains(KEY_LOCAL) || !preferences.contains(KEY_EXTERNAL)) {
            return null;
        }
        try {
            return new ServerConfig(
                preferences.getString(KEY_WIFI, ""),
                preferences.getString(KEY_LOCAL, ""),
                preferences.getString(KEY_EXTERNAL, "")
            );
        } catch (IllegalArgumentException ignored) {
            return null;
        }
    }

    void save(Context context) {
        context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
            .edit()
            .putString(KEY_WIFI, wifiSsid)
            .putString(KEY_LOCAL, localUrl)
            .putString(KEY_EXTERNAL, externalUrl)
            .apply();
    }

    String urlFor(ConnectionRouter.Route route) {
        return route == ConnectionRouter.Route.LOCAL ? localUrl : externalUrl;
    }

    boolean ownsUrl(String candidate) {
        return sameOrigin(localUrl, candidate) || sameOrigin(externalUrl, candidate);
    }

    static String normalizeBaseUrl(String input) {
        String safe = input == null ? "" : input.trim();
        if (safe.isEmpty()) {
            throw new IllegalArgumentException("Informe os dois endereços do servidor.");
        }
        if (!safe.matches("(?i)^https?://.*")) {
            safe = "http://" + safe;
        }
        try {
            URI uri = new URI(safe);
            String scheme = uri.getScheme() == null ? "" : uri.getScheme().toLowerCase(Locale.ROOT);
            if (!"http".equals(scheme) && !"https".equals(scheme)) {
                throw new IllegalArgumentException("Use um endereço começando com http:// ou https://.");
            }
            if (uri.getHost() == null || uri.getHost().trim().isEmpty()) {
                throw new IllegalArgumentException("O endereço do servidor não parece válido.");
            }
            String path = uri.getRawPath();
            if (path == null || "/".equals(path)) {
                path = "";
            } else {
                path = path.replaceAll("/+$", "");
            }
            URI normalized = new URI(
                scheme,
                uri.getUserInfo(),
                uri.getHost(),
                uri.getPort(),
                path,
                null,
                null
            );
            return normalized.toASCIIString();
        } catch (URISyntaxException error) {
            throw new IllegalArgumentException("O endereço do servidor não parece válido.");
        }
    }

    private static boolean sameOrigin(String base, String candidate) {
        try {
            URI left = new URI(base);
            URI right = new URI(candidate);
            return left.getScheme().equalsIgnoreCase(right.getScheme())
                && left.getHost().equalsIgnoreCase(right.getHost())
                && effectivePort(left) == effectivePort(right);
        } catch (Exception ignored) {
            return false;
        }
    }

    private static int effectivePort(URI uri) {
        if (uri.getPort() >= 0) {
            return uri.getPort();
        }
        return "https".equalsIgnoreCase(uri.getScheme()) ? 443 : 80;
    }
}
