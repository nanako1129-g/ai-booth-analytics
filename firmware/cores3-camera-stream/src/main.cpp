#include <Arduino.h>
#include <ESPmDNS.h>
#include <M5CoreS3.h>
#include <WiFi.h>
#include <esp_camera.h>
#include <esp_http_server.h>
#include <img_converters.h>

#include "secrets.h"

namespace {

constexpr char kMdnsName[] = "stackchan-camera";
constexpr uint32_t kWifiTimeoutMs = 30000;
constexpr int kJpegQuality = 75;

constexpr char kStreamContentType[] =
    "multipart/x-mixed-replace;boundary=stackchanframe";
constexpr char kStreamBoundary[] = "\r\n--stackchanframe\r\n";
constexpr char kStreamPart[] =
    "Content-Type: image/jpeg\r\nContent-Length: %u\r\n\r\n";

constexpr char kIndexHtml[] = R"HTML(
<!doctype html>
<html lang="ja">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Stack-chan Camera</title>
  <style>
    :root { color-scheme: dark; font-family: system-ui, sans-serif; }
    body { margin: 0; min-height: 100vh; display: grid; place-items: center; background: #091018; }
    main { width: min(92vw, 760px); text-align: center; }
    h1 { letter-spacing: .08em; }
    img { width: 100%; image-rendering: auto; border: 1px solid #2d4255; border-radius: 16px; background: #000; }
    p { color: #9fb1c1; }
  </style>
</head>
<body>
  <main>
    <h1>STACK-CHAN CAMERA</h1>
    <img src="/stream" alt="CoreS3 live camera stream">
    <p>320 × 240 / MJPEG / no recording / no face recognition</p>
  </main>
</body>
</html>
)HTML";

httpd_handle_t server = nullptr;
void showFatalError(const char* message);

extern const uint8_t kNormalJpgStart[] asm("_binary_data_normal_jpg_start");
extern const uint8_t kNormalJpgEnd[] asm("_binary_data_normal_jpg_end");
extern const uint8_t kBlinkJpgStart[] asm("_binary_data_blink_jpg_start");
extern const uint8_t kBlinkJpgEnd[] asm("_binary_data_blink_jpg_end");

bool drawEmbeddedJpg(const uint8_t* start, const uint8_t* end) {
    return CoreS3.Display.drawJpg(
        start,
        static_cast<size_t>(end - start),
        0,
        0);
}

void drawCameraCatScreen(bool blinking) {
    const bool drawn = blinking
        ? drawEmbeddedJpg(kBlinkJpgStart, kBlinkJpgEnd)
        : drawEmbeddedJpg(kNormalJpgStart, kNormalJpgEnd);

    if (!drawn) {
        showFatalError("Cat image failed");
    }
}

void setCommonHeaders(httpd_req_t* request) {
    httpd_resp_set_hdr(request, "Access-Control-Allow-Origin", "*");
    httpd_resp_set_hdr(request, "Cache-Control", "no-store, no-cache, must-revalidate");
    httpd_resp_set_hdr(request, "X-Content-Type-Options", "nosniff");
    httpd_resp_set_hdr(request, "X-Privacy", "no-recording-no-face-recognition");
}

esp_err_t indexHandler(httpd_req_t* request) {
    setCommonHeaders(request);
    httpd_resp_set_type(request, "text/html; charset=utf-8");
    return httpd_resp_send(request, kIndexHtml, HTTPD_RESP_USE_STRLEN);
}

esp_err_t healthHandler(httpd_req_t* request) {
    setCommonHeaders(request);
    httpd_resp_set_type(request, "text/plain; charset=utf-8");
    return httpd_resp_sendstr(request, "ok\n");
}

esp_err_t streamHandler(httpd_req_t* request) {
    setCommonHeaders(request);
    esp_err_t result = httpd_resp_set_type(request, kStreamContentType);
    if (result != ESP_OK) {
        return result;
    }

    char partHeader[96];

    while (true) {
        camera_fb_t* frame = esp_camera_fb_get();
        if (frame == nullptr) {
            Serial.println("Camera capture failed");
            result = ESP_FAIL;
            break;
        }

        uint8_t* jpegBuffer = nullptr;
        size_t jpegLength = 0;
        bool mustFreeJpeg = false;

        if (frame->format == PIXFORMAT_JPEG) {
            jpegBuffer = frame->buf;
            jpegLength = frame->len;
        } else {
            mustFreeJpeg = frame2jpg(frame, kJpegQuality, &jpegBuffer, &jpegLength);
            if (!mustFreeJpeg) {
                Serial.println("JPEG conversion failed");
                esp_camera_fb_return(frame);
                result = ESP_FAIL;
                break;
            }
        }

        result = httpd_resp_send_chunk(request, kStreamBoundary, strlen(kStreamBoundary));
        if (result == ESP_OK) {
            const int headerLength = snprintf(
                partHeader,
                sizeof(partHeader),
                kStreamPart,
                static_cast<unsigned int>(jpegLength));
            result = httpd_resp_send_chunk(request, partHeader, headerLength);
        }
        if (result == ESP_OK) {
            result = httpd_resp_send_chunk(
                request,
                reinterpret_cast<const char*>(jpegBuffer),
                jpegLength);
        }

        if (mustFreeJpeg) {
            free(jpegBuffer);
        }
        esp_camera_fb_return(frame);

        if (result != ESP_OK) {
            break;
        }

        delay(1);
    }

    return result;
}

bool startWebServer() {
    httpd_config_t config = HTTPD_DEFAULT_CONFIG();
    config.server_port = 80;
    config.max_open_sockets = 4;
    config.lru_purge_enable = true;
    config.stack_size = 8192;

    if (httpd_start(&server, &config) != ESP_OK) {
        return false;
    }

    httpd_uri_t indexUri = {};
    indexUri.uri = "/";
    indexUri.method = HTTP_GET;
    indexUri.handler = indexHandler;

    httpd_uri_t healthUri = {};
    healthUri.uri = "/health";
    healthUri.method = HTTP_GET;
    healthUri.handler = healthHandler;

    httpd_uri_t streamUri = {};
    streamUri.uri = "/stream";
    streamUri.method = HTTP_GET;
    streamUri.handler = streamHandler;

    return httpd_register_uri_handler(server, &indexUri) == ESP_OK &&
           httpd_register_uri_handler(server, &healthUri) == ESP_OK &&
           httpd_register_uri_handler(server, &streamUri) == ESP_OK;
}

void showFatalError(const char* message) {
    CoreS3.Display.fillScreen(TFT_RED);
    CoreS3.Display.setTextColor(TFT_WHITE, TFT_RED);
    CoreS3.Display.setTextSize(2);
    CoreS3.Display.setCursor(12, 90);
    CoreS3.Display.println(message);
    Serial.println(message);
}

}  // namespace

void setup() {
    Serial.begin(115200);
    delay(1500);
    Serial.println("AI Booth Analytics booting...");

    auto config = M5.config();
    CoreS3.begin(config);
    Serial.println("CoreS3 initialized");
    CoreS3.Display.fillScreen(TFT_BLACK);
    CoreS3.Display.setTextColor(TFT_WHITE, TFT_BLACK);
    CoreS3.Display.setTextSize(2);
    CoreS3.Display.setCursor(12, 18);
    CoreS3.Display.println("AI BOOTH ANALYTICS");
    CoreS3.Display.setTextSize(1);
    CoreS3.Display.println();
    CoreS3.Display.println("Starting camera...");

    Serial.println("Initializing camera...");
    if (!CoreS3.Camera.begin()) {
        showFatalError("Camera init failed");
        return;
    }
    Serial.println("Camera initialized");

    WiFi.mode(WIFI_STA);
    WiFi.setSleep(false);
    WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
    Serial.println("Connecting Wi-Fi...");
    CoreS3.Display.println("Connecting Wi-Fi...");

    const uint32_t startedAt = millis();
    while (WiFi.status() != WL_CONNECTED && millis() - startedAt < kWifiTimeoutMs) {
        delay(250);
        CoreS3.Display.print(".");
    }

    if (WiFi.status() != WL_CONNECTED) {
        Serial.printf("Wi-Fi status: %d\n", static_cast<int>(WiFi.status()));
        showFatalError("Wi-Fi failed\nCheck SSID/password");
        return;
    }
    Serial.println("Wi-Fi connected");

    if (!startWebServer()) {
        showFatalError("Web server failed");
        return;
    }

    MDNS.begin(kMdnsName);
    MDNS.addService("http", "tcp", 80);

    const String ip = WiFi.localIP().toString();
    Serial.printf("Camera ready: http://%s/\n", ip.c_str());
    Serial.printf("Stream URL:  http://%s/stream\n", ip.c_str());

    drawCameraCatScreen(false);
}

void loop() {
    CoreS3.update();
    static uint32_t lastStatusAt = 0;
    static uint32_t lastBlinkAt = 0;
    static bool blinking = false;

    if (!blinking && millis() - lastBlinkAt >= 4200) {
        drawCameraCatScreen(true);
        blinking = true;
        lastBlinkAt = millis();
    } else if (blinking && millis() - lastBlinkAt >= 140) {
        drawCameraCatScreen(false);
        blinking = false;
        lastBlinkAt = millis();
    }

    if (millis() - lastStatusAt >= 5000) {
        lastStatusAt = millis();
        Serial.printf(
            "Status: wifi=%d ip=%s\n",
            static_cast<int>(WiFi.status()),
            WiFi.localIP().toString().c_str());
    }
    delay(100);
}
