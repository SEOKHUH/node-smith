# Qwen-Image-Edit — 권장 구조

자연어 지시로 이미지를 편집하는 모델(Qwen2.5-VL 비전-언어 인코더가 원본 이미지를 "보고"
지시대로 바꾼다). 레퍼런스 이미지를 여러 장 넣어 "1번 모양대로 2번 원단으로" 같은 편집이 된다.

## 필수 로더 3종

| 역할 | 노드 | 파일(예) | 비고 |
|------|------|----------|------|
| UNET | `UnetLoaderGGUF` (또는 `UNETLoader`) | `qwen-image-edit-2511-Q8_0.gguf` | 12GB VRAM은 GGUF Q8 권장 |
| CLIP | `CLIPLoader` **type=`qwen_image`** | `qwen_2.5_vl_7b_fp8_scaled.safetensors` | type 틀리면 안 됨(추측 금지) |
| VAE | `VAELoader` | `qwen_image_vae.safetensors` | Qwen 전용 VAE |

## 권장 노드 체인

```
UnetLoaderGGUF ─ ModelSamplingAuraFlow ─ CFGNorm ─ [LoraLoaderModelOnly] ─┐
                                                                          ├─ KSampler ─ VAEDecode ─ SaveImage
CLIPLoader ─ TextEncodeQwenImageEditPlus (positive) ──────────────────────┤
LoadImage(원본) ─ FluxKontextImageScale ─ VAEEncode ──────────────────────┘
VAELoader ─────────────────────────────────────────────────────────────────
```

- **전용 노드**: `ModelSamplingAuraFlow`, `CFGNorm`는 Qwen 계열에 필요. 빼면 결과 어긋남.
- **레퍼런스 인코딩**: `TextEncodeQwenImageEditPlus`가 프롬프트 + 참조 이미지를 함께 조건화.
  여러 장 참조 시 `FluxKontextMultiReferenceLatentMethod`(index_timestep_zero)를 참조 수만큼 둔다.
- **입력 스케일**: 원본 이미지는 `FluxKontextImageScale`로 정규화 후 `VAEEncode`.

## 샘플러 권장값

| 방식 | steps | cfg | sampler | scheduler | denoise |
|------|:-----:|:---:|---------|-----------|:-------:|
| **Lightning 4-step** (빠름) | 4 | **1** | euler | simple | 1.0 |
| 일반 | 20 | 2.5~4 | euler | simple | 1.0 |

- **Lightning LoRA**(`Qwen-Image-Edit-2511-Lightning-4steps` 등)를 `LoraLoaderModelOnly`로 물리면 4스텝. 대신 **cfg=1** 필수.

## 함정 (검증으로 확인)

- **cfg=1(Lightning)에선 네거티브가 거의 무력** → 원치 않는 요소·배경·구도 등 모든 제어를 **긍정 프롬프트**에 명시.
- 단, **강한 학습 선입견은 긍정 프롬프트로도 못 누를 수 있음** → 완전한 제어가 필요하면 인페인트 등 별도 처리.
- **4스텝 Lightning은 가는 무늬(스트라이프)가 뭉개짐** → 선명하게 하려면 스텝 6~8 또는 8-step LoRA.
- **참조 이미지는 평평한 정면 사진** — 극단적 클로즈업·왜곡은 편집 시 어긋난다.
- `CLIPLoader` type은 반드시 `qwen_image` (다른 값으로 추측 금지).

## 프롬프트 패턴

- 참조 이미지를 여러 장 넣을 때는 프롬프트에서 **"image 1", "the second reference image"** 처럼
  몇 번째 이미지인지 가리키면 자동 캡션 없이도 편집 대상이 명확해진다.
- 대상을 **범용어**로 지시하면(구체적 종류를 박지 않으면) 모델이 해당 영역만 바꾸고 나머지는 보존한다.
