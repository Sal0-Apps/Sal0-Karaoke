package com.sal0.karaoke;

import android.Manifest;
import android.annotation.SuppressLint;
import android.app.DownloadManager;
import android.content.ActivityNotFoundException;
import android.content.ClipData;
import android.content.Context;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.graphics.Color;
import android.graphics.drawable.GradientDrawable;
import android.net.ConnectivityManager;
import android.net.Network;
import android.net.NetworkCapabilities;
import android.net.Uri;
import android.net.http.SslError;
import android.net.wifi.WifiInfo;
import android.net.wifi.WifiManager;
import android.os.Build;
import android.os.Bundle;
import android.os.Environment;
import android.os.Handler;
import android.os.Looper;
import android.view.Gravity;
import android.view.View;
import android.view.ViewGroup;
import android.webkit.CookieManager;
import android.webkit.SslErrorHandler;
import android.webkit.URLUtil;
import android.webkit.ValueCallback;
import android.webkit.WebChromeClient;
import android.webkit.WebResourceError;
import android.webkit.WebResourceRequest;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.Button;
import android.widget.EditText;
import android.widget.FrameLayout;
import android.widget.ImageView;
import android.widget.LinearLayout;
import android.widget.ProgressBar;
import android.widget.ScrollView;
import android.widget.TextView;
import android.widget.Toast;

import androidx.activity.ComponentActivity;
import androidx.activity.OnBackPressedCallback;

import java.net.HttpURLConnection;
import java.net.URL;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.atomic.AtomicInteger;

public class MainActivity extends ComponentActivity {
    private static final int COLOR_BACKGROUND = Color.rgb(9, 7, 20);
    private static final int COLOR_SURFACE = Color.rgb(18, 16, 36);
    private static final int COLOR_SURFACE_ALT = Color.rgb(27, 22, 49);
    private static final int COLOR_BORDER = Color.rgb(56, 45, 84);
    private static final int COLOR_TEXT = Color.rgb(248, 247, 255);
    private static final int COLOR_MUTED = Color.rgb(174, 165, 196);
    private static final int COLOR_PURPLE = Color.rgb(168, 85, 247);
    private static final int COLOR_PINK = Color.rgb(236, 72, 153);
    private static final int COLOR_CYAN = Color.rgb(34, 211, 238);
    private static final int COLOR_GREEN = Color.rgb(16, 185, 129);

    private static final int REQUEST_FILES = 1001;
    private static final int REQUEST_WIFI_PERMISSION = 1002;
    private static final int REQUEST_STORAGE_PERMISSION = 1003;

    private final Handler mainHandler = new Handler(Looper.getMainLooper());
    private final ExecutorService networkExecutor = Executors.newSingleThreadExecutor();
    private final AtomicInteger routeGeneration = new AtomicInteger();

    private FrameLayout root;
    private LinearLayout browserContainer;
    private FrameLayout webFrame;
    private WebView webView;
    private ProgressBar pageProgress;
    private TextView routeBadge;
    private LinearLayout offlineOverlay;
    private TextView offlineMessage;
    private ServerConfig config;
    private String currentBaseUrl;
    private ConnectionRouter.Route currentRoute;
    private boolean browserVisible;
    private boolean networkCallbackRegistered;
    private boolean pendingOpenAfterPermission;
    private ValueCallback<Uri[]> pendingFileCallback;
    private PendingWebDownload pendingWebDownload;

    private View customVideoView;
    private WebChromeClient.CustomViewCallback customVideoCallback;

    private ConnectivityManager connectivityManager;

    private final Runnable networkChangeRunnable = () -> reevaluateRoute(false);
    private final ConnectivityManager.NetworkCallback networkCallback =
        new ConnectivityManager.NetworkCallback() {
            @Override
            public void onAvailable(Network network) {
                scheduleRouteRefresh();
            }

            @Override
            public void onLost(Network network) {
                scheduleRouteRefresh();
            }

            @Override
            public void onCapabilitiesChanged(
                Network network,
                NetworkCapabilities networkCapabilities
            ) {
                scheduleRouteRefresh();
            }
        };

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        getWindow().setStatusBarColor(COLOR_BACKGROUND);
        getWindow().setNavigationBarColor(COLOR_BACKGROUND);

        root = new FrameLayout(this);
        root.setBackgroundColor(COLOR_BACKGROUND);
        root.setOnApplyWindowInsetsListener((view, insets) -> {
            view.setPadding(
                0,
                insets.getSystemWindowInsetTop(),
                0,
                insets.getSystemWindowInsetBottom()
            );
            return insets;
        });
        setContentView(root);

        connectivityManager =
            (ConnectivityManager) getSystemService(Context.CONNECTIVITY_SERVICE);
        registerNetworkCallback();
        getOnBackPressedDispatcher().addCallback(this, new OnBackPressedCallback(true) {
            @Override
            public void handleOnBackPressed() {
                if (handleNativeBack()) {
                    return;
                }
                setEnabled(false);
                getOnBackPressedDispatcher().onBackPressed();
            }
        });

        config = ServerConfig.load(this);
        if (config == null) {
            showSetup(true);
        } else {
            showBrowser();
        }
    }

    @Override
    protected void onResume() {
        super.onResume();
        if (browserVisible) {
            reevaluateRoute(false);
        }
    }

    @Override
    protected void onDestroy() {
        routeGeneration.incrementAndGet();
        mainHandler.removeCallbacksAndMessages(null);
        if (networkCallbackRegistered) {
            try {
                connectivityManager.unregisterNetworkCallback(networkCallback);
            } catch (Exception ignored) {
            }
        }
        destroyWebView();
        networkExecutor.shutdownNow();
        super.onDestroy();
    }

    private boolean handleNativeBack() {
        if (customVideoView != null) {
            hideCustomVideo();
            return true;
        }
        if (browserVisible && webView != null && webView.canGoBack()) {
            webView.goBack();
            return true;
        }
        return false;
    }

    private void showSetup(boolean firstRun) {
        browserVisible = false;
        routeGeneration.incrementAndGet();
        destroyWebView();
        root.removeAllViews();

        ScrollView scroll = new ScrollView(this);
        scroll.setFillViewport(true);
        scroll.setBackgroundColor(COLOR_BACKGROUND);
        LinearLayout page = verticalLayout();
        page.setPadding(dp(20), dp(28), dp(20), dp(32));
        page.setGravity(Gravity.CENTER_HORIZONTAL);
        scroll.addView(page, matchWrap());

        ImageView logo = new ImageView(this);
        logo.setImageResource(com.sal0.karaoke.R.drawable.app_icon);
        logo.setScaleType(ImageView.ScaleType.CENTER_CROP);
        LinearLayout.LayoutParams logoParams = new LinearLayout.LayoutParams(dp(92), dp(92));
        logoParams.bottomMargin = dp(14);
        page.addView(logo, logoParams);

        TextView title = text("Sal0 Karaokê", 27, COLOR_TEXT, true);
        title.setGravity(Gravity.CENTER);
        page.addView(title, matchWrap());

        TextView subtitle = text(
            firstRun
                ? "Seu servidor, no endereço certo em cada rede."
                : "Conexão do aplicativo",
            15,
            COLOR_MUTED,
            false
        );
        subtitle.setGravity(Gravity.CENTER);
        LinearLayout.LayoutParams subtitleParams = matchWrap();
        subtitleParams.topMargin = dp(5);
        subtitleParams.bottomMargin = dp(22);
        page.addView(subtitle, subtitleParams);

        LinearLayout card = verticalLayout();
        card.setPadding(dp(18), dp(18), dp(18), dp(18));
        card.setBackground(rounded(COLOR_SURFACE, COLOR_BORDER, 20));
        LinearLayout.LayoutParams cardParams = matchWrap();
        cardParams.bottomMargin = dp(14);
        page.addView(card, cardParams);

        TextView introTitle = text("Conectar automaticamente", 19, COLOR_TEXT, true);
        card.addView(introTitle, matchWrap());
        TextView intro = text(
            "Na rede Wi-Fi escolhida, o aplicativo usa o endereço local. "
                + "Fora dela, usa o endereço externo. Antes de abrir, ele confirma "
                + "qual endereço realmente está respondendo.",
            14,
            COLOR_MUTED,
            false
        );
        intro.setLineSpacing(0f, 1.18f);
        LinearLayout.LayoutParams introParams = matchWrap();
        introParams.topMargin = dp(8);
        introParams.bottomMargin = dp(18);
        card.addView(intro, introParams);

        addFieldLabel(card, "Nome da rede Wi-Fi");
        EditText wifiInput = editText("Ex.: Minha Casa");
        wifiInput.setSingleLine(true);
        wifiInput.setText(config == null ? "" : config.wifiSsid);
        card.addView(wifiInput, fieldParams());
        TextView wifiHint = text(
            "O Android pedirá acesso à localização somente para ler o nome da rede conectada.",
            12,
            COLOR_MUTED,
            false
        );
        LinearLayout.LayoutParams hintParams = matchWrap();
        hintParams.topMargin = dp(-4);
        hintParams.bottomMargin = dp(14);
        card.addView(wifiHint, hintParams);

        addFieldLabel(card, "Endereço local");
        EditText localInput = editText("Ex.: http://192.168.1.50:7860");
        localInput.setSingleLine(true);
        localInput.setInputType(
            android.text.InputType.TYPE_CLASS_TEXT
                | android.text.InputType.TYPE_TEXT_VARIATION_URI
        );
        localInput.setText(config == null ? "" : config.localUrl);
        card.addView(localInput, fieldParams());

        addFieldLabel(card, "Endereço externo");
        EditText externalInput = editText("Ex.: https://karaoke.seudominio.com");
        externalInput.setSingleLine(true);
        externalInput.setInputType(
            android.text.InputType.TYPE_CLASS_TEXT
                | android.text.InputType.TYPE_TEXT_VARIATION_URI
        );
        externalInput.setText(config == null ? "" : config.externalUrl);
        card.addView(externalInput, fieldParams());

        TextView apkHint = text(
            "A interface web acompanha as atualizações do servidor sozinha. "
                + "Quando o código nativo do Android mudar, gere e instale o APK localmente.",
            12,
            COLOR_MUTED,
            false
        );
        apkHint.setLineSpacing(0f, 1.16f);
        LinearLayout.LayoutParams apkHintParams = matchWrap();
        apkHintParams.topMargin = dp(4);
        apkHintParams.bottomMargin = dp(14);
        card.addView(apkHint, apkHintParams);

        Button save = primaryButton(firstRun ? "Conectar ao meu servidor" : "Salvar e reconectar");
        save.setOnClickListener(view -> {
            try {
                ServerConfig next = new ServerConfig(
                    wifiInput.getText().toString(),
                    localInput.getText().toString(),
                    externalInput.getText().toString()
                );
                if (next.wifiSsid.isEmpty()) {
                    throw new IllegalArgumentException("Informe o nome da sua rede Wi-Fi.");
                }
                next.save(this);
                config = next;
                pendingOpenAfterPermission = true;
                if (hasWifiNamePermission()) {
                    pendingOpenAfterPermission = false;
                    showBrowser();
                } else {
                    requestPermissions(
                        new String[]{
                            Manifest.permission.ACCESS_COARSE_LOCATION,
                            Manifest.permission.ACCESS_FINE_LOCATION
                        },
                        REQUEST_WIFI_PERMISSION
                    );
                }
            } catch (IllegalArgumentException error) {
                Toast.makeText(this, error.getMessage(), Toast.LENGTH_LONG).show();
            }
        });
        card.addView(save, new LinearLayout.LayoutParams(
            ViewGroup.LayoutParams.MATCH_PARENT,
            dp(52)
        ));

        if (!firstRun) {
            LinearLayout actions = horizontalLayout();
            LinearLayout.LayoutParams actionsParams = matchWrap();
            actionsParams.bottomMargin = dp(14);
            page.addView(actions, actionsParams);

            Button cancel = secondaryButton("Voltar ao karaokê");
            cancel.setOnClickListener(view -> showBrowser());
            actions.addView(cancel, new LinearLayout.LayoutParams(0, dp(48), 1f));
        }

        LinearLayout privacy = horizontalLayout();
        privacy.setPadding(dp(14), dp(12), dp(14), dp(12));
        privacy.setGravity(Gravity.CENTER_VERTICAL);
        privacy.setBackground(rounded(COLOR_SURFACE_ALT, COLOR_BORDER, 16));
        TextView privacyText = text(
            "A música continua sendo processada no seu servidor. O APK guarda apenas "
                + "os endereços e o nome da rede neste aparelho.",
            13,
            COLOR_MUTED,
            false
        );
        privacyText.setLineSpacing(0f, 1.16f);
        privacy.addView(privacyText, new LinearLayout.LayoutParams(0, -2, 1f));
        page.addView(privacy, matchWrap());

        root.addView(scroll, matchMatch());
    }

    private void showBrowser() {
        if (config == null) {
            showSetup(true);
            return;
        }
        browserVisible = true;
        root.removeAllViews();

        browserContainer = verticalLayout();
        browserContainer.setBackgroundColor(COLOR_BACKGROUND);
        root.addView(browserContainer, matchMatch());

        LinearLayout toolbar = horizontalLayout();
        toolbar.setGravity(Gravity.CENTER_VERTICAL);
        toolbar.setPadding(dp(12), dp(7), dp(8), dp(7));
        toolbar.setBackgroundColor(COLOR_SURFACE);
        browserContainer.addView(toolbar, new LinearLayout.LayoutParams(-1, dp(58)));

        ImageView logo = new ImageView(this);
        logo.setImageResource(com.sal0.karaoke.R.drawable.app_icon);
        logo.setScaleType(ImageView.ScaleType.CENTER_CROP);
        toolbar.addView(logo, new LinearLayout.LayoutParams(dp(38), dp(38)));

        TextView name = text("Sal0 Karaokê", 16, COLOR_TEXT, true);
        LinearLayout.LayoutParams nameParams = new LinearLayout.LayoutParams(0, -2, 1f);
        nameParams.leftMargin = dp(10);
        toolbar.addView(name, nameParams);

        routeBadge = text("● Conectando", 12, COLOR_MUTED, true);
        routeBadge.setGravity(Gravity.CENTER);
        routeBadge.setPadding(dp(10), dp(6), dp(10), dp(6));
        routeBadge.setBackground(rounded(COLOR_SURFACE_ALT, COLOR_BORDER, 18));
        LinearLayout.LayoutParams badgeParams = new LinearLayout.LayoutParams(-2, -2);
        badgeParams.rightMargin = dp(4);
        toolbar.addView(routeBadge, badgeParams);

        Button refresh = iconButton("↻", "Atualizar");
        refresh.setOnClickListener(view -> reevaluateRoute(true));
        toolbar.addView(refresh, new LinearLayout.LayoutParams(dp(44), dp(44)));

        Button settings = iconButton("⚙", "Configurações");
        settings.setOnClickListener(view -> showSetup(false));
        toolbar.addView(settings, new LinearLayout.LayoutParams(dp(44), dp(44)));

        pageProgress = new ProgressBar(
            this,
            null,
            android.R.attr.progressBarStyleHorizontal
        );
        pageProgress.setIndeterminate(true);
        pageProgress.getIndeterminateDrawable().setTint(COLOR_PURPLE);
        browserContainer.addView(pageProgress, new LinearLayout.LayoutParams(-1, dp(2)));

        webFrame = new FrameLayout(this);
        browserContainer.addView(webFrame, new LinearLayout.LayoutParams(-1, 0, 1f));

        webView = new WebView(this);
        configureWebView(webView);
        webFrame.addView(webView, matchMatch());
        buildOfflineOverlay();

        currentBaseUrl = null;
        currentRoute = null;
        reevaluateRoute(true);
    }

    @SuppressLint("SetJavaScriptEnabled")
    private void configureWebView(WebView target) {
        WebSettings settings = target.getSettings();
        settings.setJavaScriptEnabled(true);
        settings.setDomStorageEnabled(true);
        settings.setDatabaseEnabled(true);
        settings.setCacheMode(WebSettings.LOAD_NO_CACHE);
        settings.setAllowFileAccess(false);
        settings.setAllowContentAccess(true);
        settings.setAllowFileAccessFromFileURLs(false);
        settings.setAllowUniversalAccessFromFileURLs(false);
        settings.setMediaPlaybackRequiresUserGesture(false);
        settings.setSupportZoom(false);
        settings.setBuiltInZoomControls(false);
        settings.setDisplayZoomControls(false);
        settings.setUserAgentString(
            settings.getUserAgentString() + " Sal0KaraokeAndroid/" + BuildConfig.VERSION_NAME
        );
        settings.setSafeBrowsingEnabled(true);
        settings.setMixedContentMode(WebSettings.MIXED_CONTENT_COMPATIBILITY_MODE);

        CookieManager.getInstance().setAcceptCookie(true);
        CookieManager.getInstance().setAcceptThirdPartyCookies(target, false);
        target.setBackgroundColor(COLOR_BACKGROUND);
        target.setOverScrollMode(View.OVER_SCROLL_NEVER);

        target.setWebViewClient(new WebViewClient() {
            @Override
            public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest request) {
                return handleNavigation(request.getUrl().toString());
            }

            @Override
            public boolean shouldOverrideUrlLoading(WebView view, String url) {
                return handleNavigation(url);
            }

            @Override
            public void onPageStarted(WebView view, String url, android.graphics.Bitmap favicon) {
                pageProgress.setVisibility(View.VISIBLE);
            }

            @Override
            public void onPageFinished(WebView view, String url) {
                pageProgress.setVisibility(View.GONE);
                if (config != null && config.ownsUrl(url)) {
                    hideOffline();
                }
            }

            @Override
            public void onReceivedError(
                WebView view,
                WebResourceRequest request,
                WebResourceError error
            ) {
                if (request.isForMainFrame()) {
                    showOffline("A conexão com o servidor caiu. Tentando outro endereço…");
                    mainHandler.postDelayed(() -> reevaluateRoute(true), 700);
                }
            }

            @Override
            public void onReceivedSslError(
                WebView view,
                SslErrorHandler handler,
                SslError error
            ) {
                handler.cancel();
                showOffline(
                    "O certificado HTTPS do endereço externo não é válido. "
                        + "Corrija o certificado ou revise o endereço."
                );
            }
        });

        target.setWebChromeClient(new WebChromeClient() {
            @Override
            public boolean onShowFileChooser(
                WebView webView,
                ValueCallback<Uri[]> filePathCallback,
                FileChooserParams fileChooserParams
            ) {
                if (pendingFileCallback != null) {
                    pendingFileCallback.onReceiveValue(null);
                }
                pendingFileCallback = filePathCallback;
                try {
                    Intent chooser = fileChooserParams.createIntent();
                    startActivityForResult(chooser, REQUEST_FILES);
                    return true;
                } catch (ActivityNotFoundException error) {
                    pendingFileCallback = null;
                    Toast.makeText(
                        MainActivity.this,
                        "Nenhum seletor de arquivos foi encontrado.",
                        Toast.LENGTH_LONG
                    ).show();
                    return false;
                }
            }

            @Override
            public void onShowCustomView(View view, CustomViewCallback callback) {
                showCustomVideo(view, callback);
            }

            @Override
            public void onHideCustomView() {
                hideCustomVideo();
            }
        });

        target.setDownloadListener((url, userAgent, contentDisposition, mimeType, contentLength) ->
            requestWebDownload(url, userAgent, contentDisposition, mimeType)
        );
    }

    private void reevaluateRoute(boolean forceReload) {
        if (!browserVisible || config == null || webView == null) {
            return;
        }
        final int generation = routeGeneration.incrementAndGet();
        final boolean wifiConnected = isWifiConnected();
        final String ssid = getCurrentSsid();
        final List<ConnectionRouter.Route> priority =
            ConnectionRouter.priority(wifiConnected, ssid, config.wifiSsid);

        setRouteBadge("● Conectando", COLOR_MUTED, COLOR_SURFACE_ALT);
        pageProgress.setVisibility(View.VISIBLE);

        networkExecutor.execute(() -> {
            ConnectionRouter.Route resolvedRoute = null;
            String resolvedBase = null;
            for (ConnectionRouter.Route route : priority) {
                if (generation != routeGeneration.get()) {
                    return;
                }
                String candidate = config.urlFor(route);
                if (probe(candidate)) {
                    resolvedRoute = route;
                    resolvedBase = candidate;
                    break;
                }
            }
            final ConnectionRouter.Route route = resolvedRoute;
            final String base = resolvedBase;
            mainHandler.post(() -> {
                if (generation != routeGeneration.get() || !browserVisible) {
                    return;
                }
                if (route == null || base == null) {
                    pageProgress.setVisibility(View.GONE);
                    setRouteBadge("● Sem conexão", Color.rgb(248, 113, 113), COLOR_SURFACE_ALT);
                    String networkDescription = wifiConnected
                        ? "Wi-Fi atual: " + (
                            ConnectionRouter.isUnknownSsid(ssid)
                                ? "nome indisponível"
                                : ConnectionRouter.normalizeSsid(ssid)
                        )
                        : "O aparelho não está usando Wi-Fi.";
                    showOffline(
                        "Nenhum dos dois endereços respondeu.\n\n" + networkDescription
                    );
                    return;
                }

                boolean changed = !base.equals(currentBaseUrl);
                currentBaseUrl = base;
                currentRoute = route;
                updateRouteBadge(route, ssid);
                if (forceReload || changed || webView.getUrl() == null) {
                    loadServer(base);
                } else {
                    pageProgress.setVisibility(View.GONE);
                }
            });
        });
    }

    private boolean probe(String baseUrl) {
        HttpURLConnection connection = null;
        try {
            String probeUrl = baseUrl + "/api/auth_status?native_probe=" + System.currentTimeMillis();
            connection = (HttpURLConnection) new URL(probeUrl).openConnection();
            connection.setConnectTimeout(3500);
            connection.setReadTimeout(3500);
            connection.setUseCaches(false);
            connection.setInstanceFollowRedirects(true);
            connection.setRequestProperty("Accept", "application/json,text/plain,*/*");
            connection.setRequestProperty("Cache-Control", "no-cache");
            connection.setRequestProperty(
                "User-Agent",
                "Sal0KaraokeAndroid/" + BuildConfig.VERSION_NAME
            );
            int status = connection.getResponseCode();
            return status >= 200 && status < 500;
        } catch (Exception ignored) {
            return false;
        } finally {
            if (connection != null) {
                connection.disconnect();
            }
        }
    }

    private void loadServer(String baseUrl) {
        hideOffline();
        Map<String, String> headers = new HashMap<>();
        headers.put("Cache-Control", "no-cache, no-store, max-age=0");
        headers.put("Pragma", "no-cache");
        webView.loadUrl(baseUrl + "/", headers);
    }

    private boolean handleNavigation(String url) {
        if (url == null || url.startsWith("about:") || url.startsWith("blob:")
            || url.startsWith("data:")) {
            return false;
        }
        if (config != null && config.ownsUrl(url)) {
            return false;
        }
        try {
            Intent external = new Intent(Intent.ACTION_VIEW, Uri.parse(url));
            startActivity(external);
        } catch (Exception error) {
            Toast.makeText(this, "Não foi possível abrir esse link.", Toast.LENGTH_SHORT).show();
        }
        return true;
    }

    private void buildOfflineOverlay() {
        offlineOverlay = verticalLayout();
        offlineOverlay.setGravity(Gravity.CENTER);
        offlineOverlay.setPadding(dp(24), dp(24), dp(24), dp(24));
        offlineOverlay.setBackground(rounded(COLOR_SURFACE, COLOR_BORDER, 22));
        offlineOverlay.setVisibility(View.GONE);

        TextView icon = text("🎤", 38, COLOR_TEXT, false);
        icon.setGravity(Gravity.CENTER);
        offlineOverlay.addView(icon, matchWrap());
        TextView heading = text("Servidor fora de alcance", 19, COLOR_TEXT, true);
        heading.setGravity(Gravity.CENTER);
        LinearLayout.LayoutParams headingParams = matchWrap();
        headingParams.topMargin = dp(10);
        offlineOverlay.addView(heading, headingParams);

        offlineMessage = text("", 14, COLOR_MUTED, false);
        offlineMessage.setGravity(Gravity.CENTER);
        offlineMessage.setLineSpacing(0f, 1.15f);
        LinearLayout.LayoutParams messageParams = matchWrap();
        messageParams.topMargin = dp(8);
        messageParams.bottomMargin = dp(18);
        offlineOverlay.addView(offlineMessage, messageParams);

        Button retry = primaryButton("Tentar novamente");
        retry.setOnClickListener(view -> reevaluateRoute(true));
        offlineOverlay.addView(retry, new LinearLayout.LayoutParams(-1, dp(48)));

        Button settings = secondaryButton("Revisar endereços");
        settings.setOnClickListener(view -> showSetup(false));
        LinearLayout.LayoutParams settingsParams = new LinearLayout.LayoutParams(-1, dp(46));
        settingsParams.topMargin = dp(9);
        offlineOverlay.addView(settings, settingsParams);

        FrameLayout.LayoutParams overlayParams = new FrameLayout.LayoutParams(
            Math.min(dp(360), getResources().getDisplayMetrics().widthPixels - dp(40)),
            ViewGroup.LayoutParams.WRAP_CONTENT,
            Gravity.CENTER
        );
        webFrame.addView(offlineOverlay, overlayParams);
    }

    private void showOffline(String message) {
        if (offlineOverlay == null) {
            return;
        }
        offlineMessage.setText(message);
        offlineOverlay.setVisibility(View.VISIBLE);
        offlineOverlay.bringToFront();
    }

    private void hideOffline() {
        if (offlineOverlay != null) {
            offlineOverlay.setVisibility(View.GONE);
        }
    }

    private void updateRouteBadge(ConnectionRouter.Route route, String ssid) {
        if (route == ConnectionRouter.Route.LOCAL) {
            String label = ConnectionRouter.ssidMatches(ssid, config.wifiSsid)
                ? "● Local"
                : "● Local verificado";
            setRouteBadge(label, COLOR_CYAN, Color.rgb(12, 48, 60));
            routeBadge.setContentDescription(
                "Conectado pelo endereço local em "
                    + (
                        ConnectionRouter.isUnknownSsid(ssid)
                            ? "uma rede Wi-Fi"
                            : ConnectionRouter.normalizeSsid(ssid)
                    )
            );
        } else {
            setRouteBadge("● Externo", Color.rgb(244, 114, 182), Color.rgb(59, 20, 52));
            routeBadge.setContentDescription("Conectado pelo endereço externo");
        }
    }

    private void setRouteBadge(String label, int textColor, int backgroundColor) {
        if (routeBadge == null) {
            return;
        }
        routeBadge.setText(label);
        routeBadge.setTextColor(textColor);
        routeBadge.setBackground(rounded(backgroundColor, COLOR_BORDER, 18));
    }

    private boolean isWifiConnected() {
        try {
            Network active = connectivityManager.getActiveNetwork();
            NetworkCapabilities capabilities = connectivityManager.getNetworkCapabilities(active);
            return capabilities != null
                && capabilities.hasTransport(NetworkCapabilities.TRANSPORT_WIFI);
        } catch (Exception ignored) {
            return false;
        }
    }

    @SuppressWarnings("deprecation")
    private String getCurrentSsid() {
        if (!isWifiConnected() || !hasWifiNamePermission()) {
            return "";
        }
        try {
            WifiManager wifiManager = (WifiManager) getApplicationContext()
                .getSystemService(Context.WIFI_SERVICE);
            WifiInfo info = wifiManager.getConnectionInfo();
            return info == null ? "" : ConnectionRouter.normalizeSsid(info.getSSID());
        } catch (SecurityException ignored) {
            return "";
        }
    }

    private boolean hasWifiNamePermission() {
        return checkSelfPermission(Manifest.permission.ACCESS_FINE_LOCATION)
            == PackageManager.PERMISSION_GRANTED;
    }

    private void registerNetworkCallback() {
        if (networkCallbackRegistered) {
            return;
        }
        try {
            connectivityManager.registerDefaultNetworkCallback(networkCallback);
            networkCallbackRegistered = true;
        } catch (Exception ignored) {
        }
    }

    private void scheduleRouteRefresh() {
        mainHandler.removeCallbacks(networkChangeRunnable);
        mainHandler.postDelayed(networkChangeRunnable, 450);
    }

    private void requestWebDownload(
        String url,
        String userAgent,
        String contentDisposition,
        String mimeType
    ) {
        PendingWebDownload pending = new PendingWebDownload(
            url,
            userAgent,
            contentDisposition,
            mimeType
        );
        if (Build.VERSION.SDK_INT <= Build.VERSION_CODES.P
            && checkSelfPermission(Manifest.permission.WRITE_EXTERNAL_STORAGE)
                != PackageManager.PERMISSION_GRANTED) {
            pendingWebDownload = pending;
            requestPermissions(
                new String[]{Manifest.permission.WRITE_EXTERNAL_STORAGE},
                REQUEST_STORAGE_PERMISSION
            );
            return;
        }
        enqueueWebDownload(pending);
    }

    private void enqueueWebDownload(PendingWebDownload download) {
        try {
            String fileName = URLUtil.guessFileName(
                download.url,
                download.contentDisposition,
                download.mimeType
            ).replaceAll("[\\\\/:*?\"<>|]", "_");
            DownloadManager.Request request = new DownloadManager.Request(Uri.parse(download.url))
                .setTitle(fileName)
                .setDescription("Baixando do Sal0 Karaokê")
                .setNotificationVisibility(
                    DownloadManager.Request.VISIBILITY_VISIBLE_NOTIFY_COMPLETED
                )
                .setDestinationInExternalPublicDir(Environment.DIRECTORY_DOWNLOADS, fileName);
            if (download.mimeType != null && !download.mimeType.isEmpty()) {
                request.setMimeType(download.mimeType);
            }
            if (download.userAgent != null) {
                request.addRequestHeader("User-Agent", download.userAgent);
            }
            String cookies = CookieManager.getInstance().getCookie(download.url);
            if (cookies != null && !cookies.isEmpty()) {
                request.addRequestHeader("Cookie", cookies);
            }
            request.addRequestHeader("Referer", webView == null ? "" : webView.getUrl());
            DownloadManager manager =
                (DownloadManager) getSystemService(Context.DOWNLOAD_SERVICE);
            manager.enqueue(request);
            Toast.makeText(
                this,
                "Download iniciado. O arquivo ficará em Downloads.",
                Toast.LENGTH_LONG
            ).show();
        } catch (Exception error) {
            Toast.makeText(this, "Não foi possível iniciar o download.", Toast.LENGTH_LONG).show();
        }
    }

    private void showCustomVideo(View view, WebChromeClient.CustomViewCallback callback) {
        if (customVideoView != null) {
            callback.onCustomViewHidden();
            return;
        }
        customVideoView = view;
        customVideoCallback = callback;
        browserContainer.setVisibility(View.GONE);
        FrameLayout.LayoutParams params = matchMatch();
        root.addView(view, params);
        view.setBackgroundColor(Color.BLACK);
        getWindow().getDecorView().setSystemUiVisibility(
            View.SYSTEM_UI_FLAG_FULLSCREEN
                | View.SYSTEM_UI_FLAG_HIDE_NAVIGATION
                | View.SYSTEM_UI_FLAG_IMMERSIVE_STICKY
        );
    }

    private void hideCustomVideo() {
        if (customVideoView == null) {
            return;
        }
        root.removeView(customVideoView);
        customVideoView = null;
        if (customVideoCallback != null) {
            customVideoCallback.onCustomViewHidden();
            customVideoCallback = null;
        }
        browserContainer.setVisibility(View.VISIBLE);
        getWindow().getDecorView().setSystemUiVisibility(View.SYSTEM_UI_FLAG_VISIBLE);
    }

    private void destroyWebView() {
        if (webView == null) {
            return;
        }
        webView.stopLoading();
        webView.setWebChromeClient(null);
        webView.setWebViewClient(null);
        webView.removeAllViews();
        webView.destroy();
        webView = null;
    }

    @Override
    protected void onActivityResult(int requestCode, int resultCode, Intent data) {
        super.onActivityResult(requestCode, resultCode, data);
        if (requestCode != REQUEST_FILES || pendingFileCallback == null) {
            return;
        }
        Uri[] result = null;
        if (resultCode == RESULT_OK && data != null) {
            if (data.getClipData() != null) {
                ClipData clipData = data.getClipData();
                result = new Uri[clipData.getItemCount()];
                for (int index = 0; index < clipData.getItemCount(); index++) {
                    result[index] = clipData.getItemAt(index).getUri();
                }
            } else if (data.getData() != null) {
                result = new Uri[]{data.getData()};
            } else {
                result = WebChromeClient.FileChooserParams.parseResult(resultCode, data);
            }
        }
        pendingFileCallback.onReceiveValue(result);
        pendingFileCallback = null;
    }

    @Override
    public void onRequestPermissionsResult(
        int requestCode,
        String[] permissions,
        int[] grantResults
    ) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults);
        if (requestCode == REQUEST_WIFI_PERMISSION && pendingOpenAfterPermission) {
            pendingOpenAfterPermission = false;
            if (grantResults.length == 0 || grantResults[0] != PackageManager.PERMISSION_GRANTED) {
                Toast.makeText(
                    this,
                    "Sem essa permissão, o app tentará o endereço local quando houver Wi-Fi, "
                        + "mas não poderá conferir o nome da rede.",
                    Toast.LENGTH_LONG
                ).show();
            }
            showBrowser();
        } else if (requestCode == REQUEST_STORAGE_PERMISSION) {
            PendingWebDownload pending = pendingWebDownload;
            pendingWebDownload = null;
            if (pending != null && grantResults.length > 0
                && grantResults[0] == PackageManager.PERMISSION_GRANTED) {
                enqueueWebDownload(pending);
            } else {
                Toast.makeText(
                    this,
                    "Permita o armazenamento para salvar o vídeo em Downloads.",
                    Toast.LENGTH_LONG
                ).show();
            }
        }
    }

    private void addFieldLabel(LinearLayout parent, String label) {
        TextView fieldLabel = text(label, 13, COLOR_TEXT, true);
        LinearLayout.LayoutParams params = matchWrap();
        params.bottomMargin = dp(7);
        parent.addView(fieldLabel, params);
    }

    private EditText editText(String hint) {
        EditText edit = new EditText(this);
        edit.setHint(hint);
        edit.setHintTextColor(Color.rgb(113, 104, 139));
        edit.setTextColor(COLOR_TEXT);
        edit.setTextSize(15);
        edit.setPadding(dp(14), 0, dp(14), 0);
        edit.setBackground(rounded(Color.rgb(12, 10, 27), COLOR_BORDER, 13));
        return edit;
    }

    private LinearLayout.LayoutParams fieldParams() {
        LinearLayout.LayoutParams params = new LinearLayout.LayoutParams(-1, dp(52));
        params.bottomMargin = dp(14);
        return params;
    }

    private Button primaryButton(String label) {
        Button button = new Button(this);
        button.setText(label);
        button.setTextColor(Color.WHITE);
        button.setTextSize(14);
        button.setAllCaps(false);
        button.setTypeface(android.graphics.Typeface.DEFAULT_BOLD);
        GradientDrawable gradient = new GradientDrawable(
            GradientDrawable.Orientation.LEFT_RIGHT,
            new int[]{Color.rgb(109, 40, 217), COLOR_PINK}
        );
        gradient.setCornerRadius(dp(14));
        button.setBackground(gradient);
        return button;
    }

    private Button secondaryButton(String label) {
        Button button = new Button(this);
        button.setText(label);
        button.setTextColor(COLOR_TEXT);
        button.setTextSize(13);
        button.setAllCaps(false);
        button.setTypeface(android.graphics.Typeface.DEFAULT_BOLD);
        button.setBackground(rounded(COLOR_SURFACE_ALT, COLOR_BORDER, 13));
        return button;
    }

    private Button iconButton(String label, String description) {
        Button button = secondaryButton(label);
        button.setTextSize(20);
        button.setContentDescription(description);
        button.setPadding(0, 0, 0, 0);
        button.setBackgroundColor(Color.TRANSPARENT);
        return button;
    }

    private TextView text(String value, int sizeSp, int color, boolean bold) {
        TextView view = new TextView(this);
        view.setText(value);
        view.setTextSize(sizeSp);
        view.setTextColor(color);
        if (bold) {
            view.setTypeface(android.graphics.Typeface.DEFAULT_BOLD);
        }
        return view;
    }

    private LinearLayout verticalLayout() {
        LinearLayout layout = new LinearLayout(this);
        layout.setOrientation(LinearLayout.VERTICAL);
        return layout;
    }

    private LinearLayout horizontalLayout() {
        LinearLayout layout = new LinearLayout(this);
        layout.setOrientation(LinearLayout.HORIZONTAL);
        return layout;
    }

    private GradientDrawable rounded(int fillColor, int strokeColor, int radiusDp) {
        GradientDrawable drawable = new GradientDrawable();
        drawable.setColor(fillColor);
        drawable.setCornerRadius(dp(radiusDp));
        drawable.setStroke(dp(1), strokeColor);
        return drawable;
    }

    private int dp(int value) {
        return Math.round(value * getResources().getDisplayMetrics().density);
    }

    private LinearLayout.LayoutParams matchWrap() {
        return new LinearLayout.LayoutParams(
            ViewGroup.LayoutParams.MATCH_PARENT,
            ViewGroup.LayoutParams.WRAP_CONTENT
        );
    }

    private FrameLayout.LayoutParams matchMatch() {
        return new FrameLayout.LayoutParams(
            ViewGroup.LayoutParams.MATCH_PARENT,
            ViewGroup.LayoutParams.MATCH_PARENT
        );
    }

    private static final class PendingWebDownload {
        final String url;
        final String userAgent;
        final String contentDisposition;
        final String mimeType;

        PendingWebDownload(
            String url,
            String userAgent,
            String contentDisposition,
            String mimeType
        ) {
            this.url = url;
            this.userAgent = userAgent;
            this.contentDisposition = contentDisposition;
            this.mimeType = mimeType;
        }
    }
}
