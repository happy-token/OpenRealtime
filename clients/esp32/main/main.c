/*
 * OpenRealtime ESP32 reference client — demo-grade, mirrors clients/websocket/client.py
 * but over real hardware. Connects over WebSocket, performs the
 * SessionHelloFrame/SessionAckFrame handshake (see
 * voiceagent/endpoint_session/registry.py), sends one scripted UserTextFrame,
 * and logs whatever AssistantTextFrame/AssistantAudioChunkFrame frames come
 * back (see voiceagent/transport/frames.py for the wire schema this mirrors).
 *
 * Audio capture (I2S mic -> AudioChunkFrame) and playback
 * (AssistantAudioChunkFrame -> I2S DAC/amp) are intentionally stubbed out —
 * see README.md. This file's job is to prove the wire protocol round-trips
 * from real hardware, not to be shippable firmware (same "reference, not
 * production-grade" caveat every InMemory* default in this repo carries).
 */

#include <string.h>

#include "cJSON.h"
#include "esp_event.h"
#include "esp_log.h"
#include "esp_netif.h"
#include "esp_websocket_client.h"
#include "esp_wifi.h"
#include "nvs_flash.h"

static const char *TAG = "voiceagent_client";
static esp_websocket_client_handle_t s_client;

static void send_json(esp_websocket_client_handle_t client, cJSON *frame)
{
    char *text = cJSON_PrintUnformatted(frame);
    esp_websocket_client_send_text(client, text, strlen(text), portMAX_DELAY);
    cJSON_free(text);
    cJSON_Delete(frame);
}

static void send_session_hello(esp_websocket_client_handle_t client)
{
    cJSON *frame = cJSON_CreateObject();
    cJSON_AddStringToObject(frame, "type", "session_hello");
    send_json(client, frame);
}

/* Demo turn only: a real firmware would send this after its own ASR
 * finalizes a transcript, or stream AudioChunkFrame instead and let the
 * server-side AsrEngine transcribe it (see speech/asr.py). */
static void send_demo_user_text(esp_websocket_client_handle_t client, const char *text)
{
    cJSON *frame = cJSON_CreateObject();
    cJSON_AddStringToObject(frame, "type", "user_text");
    cJSON_AddStringToObject(frame, "text", text);
    send_json(client, frame);
}

static void handle_frame(const char *data, int len)
{
    cJSON *json = cJSON_ParseWithLength(data, len);
    if (json == NULL) {
        ESP_LOGW(TAG, "dropping non-JSON frame (%d bytes)", len);
        return;
    }

    const cJSON *type = cJSON_GetObjectItemCaseSensitive(json, "type");
    if (!cJSON_IsString(type)) {
        cJSON_Delete(json);
        return;
    }

    if (strcmp(type->valuestring, "session_ack") == 0) {
        const cJSON *session_id = cJSON_GetObjectItemCaseSensitive(json, "session_id");
        ESP_LOGI(TAG, "session_ack session_id=%s", cJSON_GetStringValue(session_id));
    } else if (strcmp(type->valuestring, "assistant_text") == 0) {
        const cJSON *text = cJSON_GetObjectItemCaseSensitive(json, "text");
        ESP_LOGI(TAG, "assistant_text: %s", cJSON_GetStringValue(text));
    } else if (strcmp(type->valuestring, "assistant_audio_chunk") == 0) {
        /* Not decoded/played here — a real firmware would base64-decode
         * pcm16_base64 and feed it to an I2S DAC/amp. See README.md. */
        const cJSON *sequence = cJSON_GetObjectItemCaseSensitive(json, "sequence");
        ESP_LOGI(TAG, "assistant_audio_chunk sequence=%d (playback not implemented)",
                 sequence->valueint);
    } else {
        ESP_LOGI(TAG, "unhandled frame type=%s", type->valuestring);
    }

    cJSON_Delete(json);
}

static void websocket_event_handler(void *handler_args, esp_event_base_t base, int32_t event_id,
                                     void *event_data)
{
    (void)handler_args;
    (void)base;
    esp_websocket_event_data_t *data = (esp_websocket_event_data_t *)event_data;

    switch (event_id) {
    case WEBSOCKET_EVENT_CONNECTED:
        ESP_LOGI(TAG, "connected to %s", CONFIG_VOICEAGENT_SERVER_URI);
        send_session_hello(s_client);
        send_demo_user_text(s_client, "hello from esp32");
        break;
    case WEBSOCKET_EVENT_DATA:
        if (data->op_code == 0x01 /* text frame */) {
            handle_frame(data->data_ptr, data->data_len);
        }
        break;
    case WEBSOCKET_EVENT_ERROR:
        ESP_LOGW(TAG, "websocket error");
        break;
    case WEBSOCKET_EVENT_DISCONNECTED:
        ESP_LOGW(TAG, "disconnected");
        break;
    default:
        break;
    }
}

static void wifi_init(void)
{
    ESP_ERROR_CHECK(esp_netif_init());
    ESP_ERROR_CHECK(esp_event_loop_create_default());
    esp_netif_create_default_wifi_sta();

    wifi_init_config_t cfg = WIFI_INIT_CONFIG_DEFAULT();
    ESP_ERROR_CHECK(esp_wifi_init(&cfg));

    wifi_config_t wifi_config = {
        .sta = {
            .ssid = CONFIG_VOICEAGENT_WIFI_SSID,
            .password = CONFIG_VOICEAGENT_WIFI_PASSWORD,
        },
    };
    ESP_ERROR_CHECK(esp_wifi_set_mode(WIFI_MODE_STA));
    ESP_ERROR_CHECK(esp_wifi_set_config(WIFI_IF_STA, &wifi_config));
    ESP_ERROR_CHECK(esp_wifi_start());
    ESP_ERROR_CHECK(esp_wifi_connect());
}

void app_main(void)
{
    ESP_ERROR_CHECK(nvs_flash_init());
    wifi_init();

    esp_websocket_client_config_t ws_cfg = {
        .uri = CONFIG_VOICEAGENT_SERVER_URI,
    };
    s_client = esp_websocket_client_init(&ws_cfg);
    esp_websocket_register_events(s_client, WEBSOCKET_EVENT_ANY, websocket_event_handler, NULL);
    esp_websocket_client_start(s_client);
}
