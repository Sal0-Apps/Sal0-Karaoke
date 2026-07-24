package com.sal0.karaoke;

import java.util.Arrays;
import java.util.List;
import java.util.Locale;

final class ConnectionRouter {
    enum Route {
        LOCAL,
        EXTERNAL
    }

    private ConnectionRouter() {
    }

    static List<Route> priority(boolean wifiConnected, String currentSsid, String configuredSsid) {
        if (wifiConnected && (ssidMatches(currentSsid, configuredSsid) || isUnknownSsid(currentSsid))) {
            return Arrays.asList(Route.LOCAL, Route.EXTERNAL);
        }
        return Arrays.asList(Route.EXTERNAL, Route.LOCAL);
    }

    static boolean ssidMatches(String currentSsid, String configuredSsid) {
        String current = normalizeSsid(currentSsid);
        String configured = normalizeSsid(configuredSsid);
        return !current.isEmpty()
            && !configured.isEmpty()
            && current.toLowerCase(Locale.ROOT).equals(configured.toLowerCase(Locale.ROOT));
    }

    static boolean isUnknownSsid(String value) {
        String normalized = normalizeSsid(value);
        return normalized.isEmpty() || "<unknown ssid>".equalsIgnoreCase(normalized);
    }

    static String normalizeSsid(String value) {
        if (value == null) {
            return "";
        }
        String normalized = value.trim();
        if (normalized.length() >= 2 && normalized.startsWith("\"") && normalized.endsWith("\"")) {
            normalized = normalized.substring(1, normalized.length() - 1);
        }
        return normalized.trim();
    }
}
