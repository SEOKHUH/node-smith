# WAN 2.2 First-Last-Frame (FLF) — 권장 구조

**시작 이미지 + 끝 이미지**를 주면 그 사이를 부드럽게 잇는 영상을 만든다(WAN 2.2 I2V 14B).

## 필수: Hi-Lo 이중 구조

WAN 2.2 I2V는 **HighNoise / LowNoise 두 모델을 반드시 함께** 쓴다(2단 `KSamplerAdvanced`).
하나만 쓰면 결과가 무너진다.

- **HighNoise**(pass1, 0→N/2): 구조·모션·구도
- **LowNoise**(pass2, N/2→N): 디테일·입력 프레임 충실도
- 두 패스는 `WanFirstLastFrameToVideo`의 같은 조건을 공유, pass1의 noisy latent를 pass2가 이어받음

## 로더 (Hi/Lo 항상 둘 다)

| 역할 | 노드 | 파일(공식 fp8) |
|------|------|----------------|
| UNET(High) | `UNETLoader` | `wan2.2_i2v_high_noise_14B_fp8_scaled.safetensors` |
| UNET(Low) | `UNETLoader` | `wan2.2_i2v_low_noise_14B_fp8_scaled.safetensors` |
| CLIP(T5) | `CLIPLoader` **type=`wan`** | `umt5_xxl_fp8_e4m3fn_scaled.safetensors` |
| CLIP Vision | `CLIPVisionLoader` | `clip_vision_h.safetensors` |
| VAE | `VAELoader` | `wan_2.1_vae.safetensors` |

> GGUF Q8 대안: `Wan2.2-I2V-A14B-HighNoise/LowNoise-Q8_0.gguf` + `UnetLoaderGGUF`(외부 Lightning LoRA 필요).

## 필수 노드: ModelSamplingSD3

WAN 2.2는 flow matching이라 **각 UNET에 `ModelSamplingSD3`** 를 붙인다:

```
ModelSamplingSD3: shift=5 (lightning) / shift=8 (표준 비-lightning)
```

## 권장 노드 체인

```
UNETLoader(High) ─ ModelSamplingSD3 ─ [Lightning LoRA High] ─┐
CLIPLoader(wan) ─ CLIPTextEncode(pos/neg) ──┐                │
LoadImage(start)/LoadImage(end) ─ CLIPVisionLoader ─ WanFirstLastFrameToVideo ─┤
                                                              ├─ KSamplerAdvanced(pass1, add_noise=enable)
                                                              │        │ (noisy latent)
UNETLoader(Low) ─ ModelSamplingSD3 ─ [Lightning LoRA Low] ── KSamplerAdvanced(pass2, add_noise=disable) ─ VAEDecode ─ (영상)
VAELoader ────────────────────────────────────────────────────
```

## 샘플러 권장값

| 방식 | steps | shift | LoRA |
|------|:-----:|:-----:|------|
| **Lightning 4-step** | 4 (2+2) | 5 | Hi/Lo lightning 짝 |
| 표준 | 더 많이 | 8 | 없음 |

## 함정

- **Hi/Lo 둘 다 필수** — 단일 KSampler·단일 모델 금지(2.1과 다름).
- **각 UNET에 ModelSamplingSD3** 안 붙이면 안 됨(flow matching).
- 이미지→영상은 FLF/I2V, 텍스트→영상은 별도(`wan-t2v-video`).
- CLIP Vision(`clip_vision_h`)이 시작/끝 프레임 인코딩에 필요.

> 정답지 JSON은 추후 실제 생성·검증하며 추가.
