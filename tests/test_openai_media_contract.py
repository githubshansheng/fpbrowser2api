from __future__ import annotations

import asyncio
import base64
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import HTTPException

from src.api import routes
from src.services import veo_workflow_executor as veo
from src.services.task_executor_types import NonPenalizedTaskError


AUTH_HEADERS = {"Authorization": "Bearer contract-test-api-key"}


def assert_openai_error(response, status_code: int) -> dict[str, Any]:
    assert response.status_code == status_code, response.text
    body = response.json()
    assert set(body) == {"error"}
    assert isinstance(body["error"], dict)
    assert isinstance(body["error"].get("message"), str)
    assert body["error"]["message"]
    assert "type" in body["error"]
    assert "param" in body["error"]
    assert "code" in body["error"]
    return body["error"]


def completed_image_task(url: str = "https://cdn.example.test/edited.png"):
    now = datetime(2026, 8, 11, tzinfo=timezone.utc)
    return SimpleNamespace(
        task_id="image-task-1",
        status="completed",
        progress=100,
        result={"workflow_kind": "image", "image_url": url},
        error_message=None,
        created_at=now,
        completed_at=now,
    )


def install_successful_image_task_stubs(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    captured: dict[str, Any] = {}

    async def fake_create_task(request):
        captured["request"] = request
        return {"success": True, "task_id": "image-task-1"}

    async def fake_wait(task_id: str, timeout_sec: float, poll_interval_sec: float):
        captured["wait"] = (task_id, timeout_sec, poll_interval_sec)
        return completed_image_task()

    monkeypatch.setattr(routes, "_create_task_from_request", fake_create_task)
    monkeypatch.setattr(routes, "_wait_for_task_final", fake_wait)
    return captured


def install_fake_upload_cache(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """Return deterministic asset URLs without writing into the real static cache."""

    calls: list[dict[str, Any]] = []

    async def fake_cache(data: bytes, *, content_type: str, source_label: str) -> str:
        calls.append(
            {
                "data": data,
                "content_type": content_type,
                "source_label": source_label,
            }
        )
        return f"https://assets.example.test/{len(calls)}.png"

    monkeypatch.setattr(routes, "cache_public_api_image_bytes", fake_cache)
    return calls


def payload_images(payload: dict[str, Any]) -> list[Any]:
    value = payload.get("images", payload.get("image"))
    if isinstance(value, list):
        return value
    return [] if value is None else [value]


def test_image_edits_accepts_json_image_urls(client, monkeypatch: pytest.MonkeyPatch):
    captured = install_successful_image_task_stubs(monkeypatch)
    image_urls = [
        "https://images.example.test/source-1.png",
        "https://images.example.test/source-2.png",
    ]

    response = client.post(
        "/v1/images/edits",
        headers=AUTH_HEADERS,
        json={
            "model": "nana-banana-2_sync",
            "prompt": "replace the background",
            "image": image_urls,
            "n": 1,
            "response_format": "url",
        },
    )

    assert response.status_code == 200, response.text
    assert response.json()["data"] == [{"url": "https://cdn.example.test/edited.png"}]
    submitted = captured["request"]
    assert submitted.task_type_code
    assert submitted.json["prompt"] == "replace the background"
    assert payload_images(submitted.json) == image_urls
    assert captured["wait"][0] == "image-task-1"


def test_image_edits_accepts_multipart_files_and_gpt_mask(client, monkeypatch: pytest.MonkeyPatch):
    captured = install_successful_image_task_stubs(monkeypatch)
    cache_calls = install_fake_upload_cache(monkeypatch)

    response = client.post(
        "/v1/images/edits",
        headers=AUTH_HEADERS,
        data={
            "model": "gpt-image2-1k_sync",
            "prompt": "edit only the masked area",
            "n": "1",
            "response_format": "url",
        },
        files=[
            ("image", ("first.png", b"first-image", "image/png")),
            ("image", ("second.webp", b"second-image", "image/webp")),
            ("mask", ("mask.png", b"mask-image", "image/png")),
        ],
    )

    assert response.status_code == 200, response.text
    submitted_payload = captured["request"].json
    assert len(payload_images(submitted_payload)) == 2
    assert submitted_payload.get("mask")
    assert [call["data"] for call in cache_calls] == [b"first-image", b"second-image", b"mask-image"]
    assert [call["content_type"] for call in cache_calls] == ["image/png", "image/webp", "image/png"]


@pytest.mark.parametrize("image_count", [0, 8])
def test_image_edits_requires_between_one_and_seven_images(
    client,
    monkeypatch: pytest.MonkeyPatch,
    image_count: int,
):
    create_called = False

    async def fake_create_task(request):
        nonlocal create_called
        create_called = True
        return {"task_id": "should-not-be-created"}

    monkeypatch.setattr(routes, "_create_task_from_request", fake_create_task)
    body: dict[str, Any] = {
        "model": "gpt-image2-1k_sync",
        "prompt": "invalid image count",
        "n": 1,
    }
    if image_count:
        body["image"] = [f"https://images.example.test/{index}.png" for index in range(image_count)]

    response = client.post("/v1/images/edits", headers=AUTH_HEADERS, json=body)

    assert_openai_error(response, 400)
    assert create_called is False


def test_image_edits_only_supports_n_one(client):
    response = client.post(
        "/v1/images/edits",
        headers=AUTH_HEADERS,
        json={
            "model": "gpt-image2-1k_sync",
            "prompt": "two variants",
            "image": "https://images.example.test/source.png",
            "n": 2,
        },
    )

    assert_openai_error(response, 400)


def test_image_edits_rejects_mask_for_nana_models(client):
    response = client.post(
        "/v1/images/edits",
        headers=AUTH_HEADERS,
        data={"model": "nana-banana-2_sync", "prompt": "masked edit", "n": "1"},
        files=[
            ("image", ("source.png", b"source-image", "image/png")),
            ("mask", ("mask.png", b"mask-image", "image/png")),
        ],
    )

    assert_openai_error(response, 400)


def test_image_edits_rejects_non_image_multipart_file(client):
    response = client.post(
        "/v1/images/edits",
        headers=AUTH_HEADERS,
        data={"model": "gpt-image2-1k_sync", "prompt": "not an image", "n": "1"},
        files=[("image", ("notes.txt", b"plain text", "text/plain"))],
    )

    assert_openai_error(response, 400)


def test_image_edits_rejects_active_svg_even_with_image_mime(client, monkeypatch: pytest.MonkeyPatch):
    create_called = False

    async def fake_create_task(request):
        nonlocal create_called
        create_called = True
        return {"task_id": "should-not-be-created"}

    monkeypatch.setattr(routes, "_create_task_from_request", fake_create_task)
    response = client.post(
        "/v1/images/edits",
        headers=AUTH_HEADERS,
        data={"model": "gpt-image2-1k_sync", "prompt": "unsafe svg", "n": "1"},
        files=[
            (
                "image",
                (
                    "active.svg",
                    b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>',
                    "image/svg+xml",
                ),
            )
        ],
    )

    assert_openai_error(response, 400)
    assert create_called is False


def test_image_edits_rejects_unknown_multipart_file_field(client, monkeypatch: pytest.MonkeyPatch):
    create_called = False

    async def fake_create_task(request):
        nonlocal create_called
        create_called = True
        return {"task_id": "should-not-be-created"}

    monkeypatch.setattr(routes, "_create_task_from_request", fake_create_task)
    response = client.post(
        "/v1/images/edits",
        headers=AUTH_HEADERS,
        data={"model": "gpt-image2-1k_sync", "prompt": "unknown file field", "n": "1"},
        files=[
            ("image", ("source.png", b"source", "image/png")),
            ("attachment", ("unexpected.png", b"unexpected", "image/png")),
        ],
    )

    error = assert_openai_error(response, 400)
    assert "unexpected file field" in error["message"]
    assert create_called is False


def test_image_edits_returns_413_when_upload_cache_rejects_size(
    client,
    monkeypatch: pytest.MonkeyPatch,
):
    create_called = False

    async def fake_cache_rejects_size(*args, **kwargs):
        raise NonPenalizedTaskError("image exceeds upload limit", status_code=413)

    async def fake_create_task(request):
        nonlocal create_called
        create_called = True
        return {"task_id": "should-not-be-created"}

    monkeypatch.setattr(routes, "cache_public_api_image_bytes", fake_cache_rejects_size)
    monkeypatch.setattr(routes, "_create_task_from_request", fake_create_task)

    response = client.post(
        "/v1/images/edits",
        headers=AUTH_HEADERS,
        data={"model": "gpt-image2-1k_sync", "prompt": "oversized upload", "n": "1"},
        files=[("image", ("large.png", b"small-test-double", "image/png"))],
    )

    assert_openai_error(response, 413)
    assert create_called is False


def test_image_edits_rejects_more_than_seven_multipart_images(client):
    response = client.post(
        "/v1/images/edits",
        headers=AUTH_HEADERS,
        data={"model": "gpt-image2-1k_sync", "prompt": "too many", "n": "1"},
        files=[
            ("image", (f"source-{index}.png", f"image-{index}".encode(), "image/png"))
            for index in range(8)
        ],
    )

    assert_openai_error(response, 400)


def test_image_generations_keeps_banana_json_image_edit_compatibility(
    client,
    monkeypatch: pytest.MonkeyPatch,
):
    captured = install_successful_image_task_stubs(monkeypatch)
    source_url = "https://images.example.test/original.png"

    response = client.post(
        "/v1/images/generations",
        headers=AUTH_HEADERS,
        json={
            "model": "nana-banana-2_sync",
            "prompt": "retain the person and change the setting",
            "image": source_url,
            "n": 1,
            "response_format": "url",
        },
    )

    assert response.status_code == 200, response.text
    assert response.json()["data"] == [{"url": "https://cdn.example.test/edited.png"}]
    assert payload_images(captured["request"].json) == [source_url]


class FakeTaskDatabase:
    def __init__(self, task):
        self.task = task

    async def get_task(self, task_id: str):
        return self.task


def video_task(status: str, result: dict[str, Any] | None = None):
    return SimpleNamespace(
        task_id="video-task-1",
        status=status,
        progress=100 if status == "completed" else 25,
        result=result,
        error_message="provider failed" if status == "failed" else None,
    )


@pytest.mark.parametrize(
    ("task", "expected_status"),
    [
        (None, 404),
        (video_task("running"), 409),
        (video_task("completed", {}), 502),
    ],
)
def test_video_content_error_contract(client, monkeypatch, task, expected_status: int):
    monkeypatch.setattr(routes, "db", FakeTaskDatabase(task))

    response = client.get("/v1/videos/video-task-1/content", headers=AUTH_HEADERS)

    assert_openai_error(response, expected_status)


@pytest.mark.parametrize("scheme", ["http", "https"])
def test_video_content_redirects_to_http_sources(client, monkeypatch, scheme: str):
    source_url = f"{scheme}://cdn.example.test/video.mp4?token=abc"
    monkeypatch.setattr(
        routes,
        "db",
        FakeTaskDatabase(video_task("completed", {"video_url": source_url})),
    )

    response = client.get(
        "/v1/videos/video-task-1/content",
        headers=AUTH_HEADERS,
        follow_redirects=False,
    )

    assert response.status_code == 307, response.text
    assert response.headers["location"] == source_url


def test_video_content_decodes_data_video(client, monkeypatch):
    video_bytes = b"contract-test-video"
    data_url = "data:video/mp4;base64," + base64.b64encode(video_bytes).decode("ascii")
    monkeypatch.setattr(
        routes,
        "db",
        FakeTaskDatabase(video_task("completed", {"video_url": data_url})),
    )

    response = client.get("/v1/videos/video-task-1/content", headers=AUTH_HEADERS)

    assert response.status_code == 200, response.text
    assert response.content == video_bytes
    assert response.headers["content-type"].startswith("video/mp4")
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["cache-control"] == "no-store"


def test_video_content_rejects_unsupported_inline_video_mime(client, monkeypatch):
    data_url = "data:video/svg+xml;base64," + base64.b64encode(b"<svg/>").decode("ascii")
    monkeypatch.setattr(
        routes,
        "db",
        FakeTaskDatabase(video_task("completed", {"video_url": data_url})),
    )

    response = client.get("/v1/videos/video-task-1/content", headers=AUTH_HEADERS)

    error = assert_openai_error(response, 502)
    assert error["code"] == "invalid_video_result"


def test_video_content_rejects_inline_video_over_limit(client, monkeypatch):
    monkeypatch.setattr(routes, "_VIDEO_CONTENT_INLINE_MAX_BYTES", 4)
    data_url = "data:video/mp4;base64," + base64.b64encode(b"12345").decode("ascii")
    monkeypatch.setattr(
        routes,
        "db",
        FakeTaskDatabase(video_task("completed", {"video_url": data_url})),
    )

    response = client.get("/v1/videos/video-task-1/content", headers=AUTH_HEADERS)

    error = assert_openai_error(response, 502)
    assert error["code"] == "video_result_too_large"


@pytest.mark.parametrize(
    "source_url",
    [
        "ftp://cdn.example.test/video.mp4",
        "file:///var/tmp/video.mp4",
        "javascript:alert(1)",
    ],
)
def test_video_content_rejects_unsupported_source_protocols(client, monkeypatch, source_url: str):
    monkeypatch.setattr(
        routes,
        "db",
        FakeTaskDatabase(video_task("completed", {"video_url": source_url})),
    )

    response = client.get("/v1/videos/video-task-1/content", headers=AUTH_HEADERS)

    assert_openai_error(response, 502)


def test_video_content_rejects_completed_image_task(client, monkeypatch):
    monkeypatch.setattr(
        routes,
        "db",
        FakeTaskDatabase(
            video_task(
                "completed",
                {
                    "workflow_kind": "image",
                    "image_url": "https://cdn.example.test/generated.png",
                    "result_urls": ["https://cdn.example.test/generated.png"],
                },
            )
        ),
    )

    response = client.get("/v1/videos/video-task-1/content", headers=AUTH_HEADERS)

    assert_openai_error(response, 502)


@pytest.mark.parametrize(
    ("method", "path", "kwargs"),
    [
        (
            "post",
            "/v1/images/edits",
            {
                "json": {
                    "model": "gpt-image2-1k_sync",
                    "prompt": "edit",
                    "image": "https://images.example.test/source.png",
                }
            },
        ),
        ("get", "/v1/videos/video-task-1/content", {}),
    ],
)
def test_new_media_routes_require_bearer_api_key(client, method: str, path: str, kwargs):
    response = getattr(client, method)(path, **kwargs)

    # Preserve the project's existing HTTPBearer semantics: an absent scheme is
    # rejected by FastAPI with 403, while a supplied but invalid token is 401.
    assert_openai_error(response, 403)


def test_new_media_routes_reject_invalid_bearer_api_key(client):
    response = client.get(
        "/v1/videos/video-task-1/content",
        headers={"Authorization": "Bearer invalid-contract-key"},
    )

    assert_openai_error(response, 401)


def test_unmatched_v1_route_uses_openai_error_envelope(client):
    response = client.get("/v1/this-route-does-not-exist", headers=AUTH_HEADERS)

    assert_openai_error(response, 404)


def test_v1_request_validation_uses_openai_error_envelope(client):
    response = client.post(
        "/v1/videos",
        headers=AUTH_HEADERS,
        json={"model": "seedance-2"},
    )

    error = assert_openai_error(response, 422)
    assert error["type"] == "invalid_request_error"


def test_v1_rate_limit_preserves_retry_after_header(client, monkeypatch: pytest.MonkeyPatch):
    async def fake_rate_limited_create(request):
        raise HTTPException(
            status_code=429,
            detail="request limit reached",
            headers={"Retry-After": "7"},
        )

    monkeypatch.setattr(routes, "_create_task_from_request", fake_rate_limited_create)

    response = client.post(
        "/v1/videos",
        headers=AUTH_HEADERS,
        json={"model": "seedance-2", "prompt": "a lighthouse"},
    )

    assert_openai_error(response, 429)
    assert response.headers["retry-after"] == "7"


def test_image_generation_missing_created_task_id_returns_openai_500(
    client,
    monkeypatch: pytest.MonkeyPatch,
):
    async def fake_create_without_task_id(request):
        return {"success": False}

    monkeypatch.setattr(routes, "_create_task_from_request", fake_create_without_task_id)

    response = client.post(
        "/v1/images/generations",
        headers=AUTH_HEADERS,
        json={
            "model": "gpt-image2-1k_sync",
            "prompt": "missing task id",
            "n": 1,
        },
    )

    error = assert_openai_error(response, 500)
    assert error["code"] == "invalid_task_response"


def test_public_safe_raster_flag_cannot_be_disabled_by_payload_or_environment(monkeypatch):
    monkeypatch.setenv("VEO_LOCAL_IMAGE_CACHE_ENABLED", "0")
    payload = {
        "public_api_safe_raster_only": True,
        "local_image_cache": False,
        "localize_extension_images": "off",
    }

    assert veo._veo_extension_local_image_cache_enabled(payload) is True


def test_local_image_lock_uses_fixed_stripes_and_same_key_is_stable():
    stripe_ids_before = tuple(id(lock) for lock in veo._VEO_LOCAL_IMAGE_LOCK_STRIPES)

    async def resolve_locks():
        same_first = await veo._veo_local_image_lock("same-cache-key")
        same_second = await veo._veo_local_image_lock("same-cache-key")
        many = [await veo._veo_local_image_lock(f"cache-key-{index}") for index in range(1024)]
        return same_first, same_second, many

    same_first, same_second, many = asyncio.run(resolve_locks())

    assert same_first is same_second
    assert len(veo._VEO_LOCAL_IMAGE_LOCK_STRIPES) == veo._VEO_LOCAL_IMAGE_LOCK_STRIPE_COUNT
    assert tuple(id(lock) for lock in veo._VEO_LOCAL_IMAGE_LOCK_STRIPES) == stripe_ids_before
    assert all(lock in veo._VEO_LOCAL_IMAGE_LOCK_STRIPES for lock in many)


def test_image_edits_openapi_limits_json_images_to_seven(client):
    operation = client.app.openapi()["paths"]["/v1/images/edits"]["post"]
    schema = operation["requestBody"]["content"]["application/json"]["schema"]
    images_schema = schema["properties"]["images"]
    array_schema = next(item for item in images_schema["anyOf"] if item.get("type") == "array")

    assert array_schema["minItems"] == 1
    assert array_schema["maxItems"] == 7
