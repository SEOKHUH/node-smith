# Qwen Image 2512 (txt2img) — 권장 구조

Qwen 계열의 텍스트→이미지 모델(2025.12). 텍스트 인코더로 Qwen2.5-VL을 쓴다.
편집(Image-Edit)이 아니라 순수 생성용. 두 방식:

- **QwenImageIntegratedKSampler** — 로딩+샘플링 올인원 노드(간단).
- **분리 컴포넌트** — `UNETLoader`+`CLIPLoader`+`VAELoader`+표준 `KSampler`(유연).

## 로더 3종 (분리 방식)

| 역할 | 노드 | 파일 |
|------|------|------|
| UNET | `UNETLoader` | `qwen_image_2512_fp8_e4m3fn.safetensors` (FP8) |
| CLIP | `CLIPLoader` **type=`qwen_image`** | `qwen_2.5_vl_7b_fp8_scaled.safetensors` (Qwen 공용) |
| VAE | `VAELoader` | `qwen_image_vae.safetensors` |

## 권장 노드 체인 (분리 방식)

```
UNETLoader ─ [LoraLoaderModelOnly] ─ [ModelSamplingAuraFlow shift=3.1] ─┐
CLIPLoader ─ CLIPTextEncode(pos) / CLIPTextEncode(neg) ─────────────────┼─ KSampler ─ VAEDecode ─ SaveImage
EmptyLatentImage ───────────────────────────────────────────────────────┘
VAELoader ────────────────────────────────────────────────────────────────
```

- **비-Lightning(표준) 프리셋**엔 `ModelSamplingAuraFlow`(shift 3.1)로 flow shift 적용.
- **Lightning LoRA**(`Qwen-Image-Lightning-4steps`/`8steps`)를 `LoraLoaderModelOnly`로 물리면 4/8스텝.

## 샘플러 권장값

| 프리셋 | steps | cfg | sampler | scheduler | LoRA |
|--------|:-----:|:---:|---------|-----------|------|
| **Lightning 4-step** | 4 | 1.0 | euler | simple | Lightning-4steps |
| **Lightning 8-step** | 8 | 1.0 | euler | simple | Lightning-8steps |
| Lightning 인물 | 8 | 2.5 | euler | simple | Lightning-8steps |
| 표준(공식) | 50 | 4.0 | euler | simple | 없음 |
| 골든 품질 | 50 | 4.5 | euler | simple | 없음 |
| 다중 인물 구성 | 30 | 4.0 | euler_ancestral | beta | 없음 |
| 초현실(제품컷) | 30 | 7.5 | euler | simple | 없음 |

## 함정

- **Lightning 쓰면 cfg=1** 필수(네거티브 무력 → 제어는 긍정으로). 인물 디테일은 8-step+cfg2.5.
- `CLIPLoader` type은 `qwen_image`. VAE는 `qwen_image_vae`(Z-Image의 `ae.safetensors`와 다름).
- 편집 모델(Qwen-Image-Edit)과 **다른 UNET** — 순수 생성이면 2512, 이미지 편집이면 Edit-2511.

> 정답지 JSON은 추후 실제 생성·검증하며 추가.
