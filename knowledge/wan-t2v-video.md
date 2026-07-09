# WAN 2.2 Text-to-Video (T2V) — 권장 구조

텍스트에서 영상을 만드는 14B MoE 모델. **전문가 UNET 2개를 이어 쓰는 게 핵심**:

- **HighNoise 모델** — 초반 디노이즈(구조·모션·구도 결정)
- **LowNoise 모델** — 후반 디노이즈(디테일·선명도)

I2V/FLF와 같은 dual 기법이되, **이미지 입력 노드가 없다**(CLIPVisionEncode·WanFirstLastFrameToVideo 안 씀).
잠재 초기화는 `EmptyHunyuanLatentVideo`, 조건은 텍스트만.

## 로더

| 역할 | 노드 | 파일 |
|------|------|------|
| UNET(High) | `UNETLoader` | `Wan2_2-T2V-A14B_HIGH_fp8_e4m3fn_scaled_KJ.safetensors` |
| UNET(Low) | `UNETLoader` | `Wan2_2-T2V-A14B-LOW_fp8_e4m3fn_scaled_KJ.safetensors` |
| CLIP(T5) | `CLIPLoader` **type=`wan`** | `umt5_xxl_fp8_e4m3fn_scaled.safetensors` |
| VAE | `VAELoader` | `wan_2.1_vae.safetensors` |

## 권장 노드 체인 (2-패스)

```
UNETLoader(High) ─ [LoraLoaderModelOnly(High Lightning)] ─┐
                                                          ├─ KSamplerAdvanced(Pass1, add_noise=enable)
CLIPLoader(wan) ─ CLIPTextEncode(pos)/(neg) ──────────────┤        │ (중간 latent)
EmptyHunyuanLatentVideo ──────────────────────────────────┘        ▼
UNETLoader(Low) ─ [LoraLoaderModelOnly(Low Lightning)] ── KSamplerAdvanced(Pass2, add_noise=disable) ─ VAEDecode ─ (영상 저장)
VAELoader ───────────────────────────────────────────────────────────
```

- **KSamplerAdvanced 2단**: Pass1은 High 모델(+ High Lightning LoRA, add_noise=enable),
  Pass2는 Low 모델(+ Low Lightning LoRA, add_noise=disable)로 이어받음.
- **Lightning LoRA는 Hi/Lo 짝**으로 각 UNET에 맞춰 물린다(High LoRA→High UNET, Low LoRA→Low UNET).

## 샘플러 권장값

| 방식 | steps | 비고 |
|------|:-----:|------|
| **Lightning 4-step**(빠름) | 4 (2+2 분할) | Hi/Lo Lightning LoRA 짝 사용 |
| CFG-step distill(고품질) | 더 많은 스텝 | `lightx2v_T2V_14B_cfg_step_distill` LoRA |

## 함정

- **High/Low UNET을 반드시 짝으로** — 하나만 쓰면 결과 무너짐. Lightning LoRA도 Hi/Lo 짝.
- `CLIPLoader` type=`wan`, VAE=`wan_2.1_vae` (다른 계열과 혼동 금지).
- T2V는 **이미지 입력 없음** — 이미지에서 영상은 I2V/FLF(별도 스킬 `wan-flf-video`).
- VRAM 큼(14B×2, FP8) — 12GB에선 해상도·프레임 보수적으로.

> 정답지 JSON은 추후 실제 생성·검증하며 추가.
