# Z-Image (txt2img) — 권장 구조

알리바바 Tongyi Lab의 6B 텍스트→이미지 모델(S3-DiT). 텍스트 인코더로 **Qwen 인코더**를 쓰고,
VAE는 **Flux와 동일한 `ae.safetensors`** 를 쓴다. 두 갈래:

- **Base / RedCraft(파인튜닝)** — 풀 모델. 네거티브 유효, ControlNet 가능. 10~30스텝.
- **Turbo** — DMD 증류. 8~10스텝, **네거티브 거의 무력**(CFG 내장).

## 로더 — 두 방식

**(A) RedCraft 합본 체크포인트 (설치됨, 가장 간단)**

| 역할 | 노드 | 파일 |
|------|------|------|
| 체크포인트(UNET+CLIP+VAE 합본) | `CheckpointLoaderSimple` | `redcraftRedzimageUpdatedJAN30_redzibDX1.safetensors` (17GB) |

→ 합본이라 별도 로더 불필요. 텍스트 인코딩은 표준 `CLIPTextEncode`(체크포인트가 토크나이저 포함).

**(B) 분리 컴포넌트 (Turbo/Base)**

| 역할 | 노드 | 파일 |
|------|------|------|
| UNET | `UNETLoader` | `z_image_turbo_bf16.safetensors` / `z_image_base_bf16.safetensors` |
| CLIP | `CLIPLoader` **type=`qwen_image`** | `qwen_3_4b.safetensors` |
| VAE | `VAELoader` | `ae.safetensors` (Flux VAE와 동일) |

→ 인코딩은 `TextEncodeZImageOmni`(참조 이미지 최대 3장·CLIP Vision 지원).

## 권장 노드 체인 (RedCraft 합본 기준)

```
CheckpointLoaderSimple ─┬─ CLIPTextEncode(positive) ─┐
                        ├─ CLIPTextEncode(negative) ─┤
                        └─ (VAE) ────────────────────┼─ KSampler ─ VAEDecode ─ SaveImage
EmptyLatentImage ────────────────────────────────────┘
```

## 샘플러 권장값

**RedCraft DX1**

| 프리셋 | steps | cfg | sampler | scheduler |
|--------|:-----:|:---:|---------|-----------|
| 빠름(증류) | 10 | 1.0 | euler | simple |
| 표준(풀품질) | 30 | 4.0 | euler | simple |

**Turbo** (560장 테스트 기준)

| 프리셋 | steps | cfg | sampler | scheduler |
|--------|:-----:|:---:|---------|-----------|
| 가장 선명 | 10 | 1.0 | dpmpp_sde | beta |
| 뷰티/패션(부드러운 피부) | 10 | 1.0 | euler_ancestral | beta |
| 저자 추천 | 14 | 1.0 | res_2s | simple |

**Base**: 22스텝 / cfg 4~7 / res_2s (2단계 구성 가능).

## 함정

- **Turbo는 네거티브 무력**(CFG 내장) → 제어는 긍정 프롬프트로. Base/RedCraft는 네거티브 유효.
- **VAE는 Flux `ae.safetensors`** — Qwen VAE와 다름(혼동 금지).
- 분리 로딩 시 `CLIPLoader` type은 `qwen_image` (추측 금지).

> ⚠️ 우리가 예전에 Z-Image-Turbo를 직접 짜다 CLIPLoader 타입·샘플러·노드 구조를 전부 틀린 적 있음
> → 반드시 이 문서(또는 live 조회)로 확인하고 짤 것. 정답지 JSON은 추후 검증하며 추가.
