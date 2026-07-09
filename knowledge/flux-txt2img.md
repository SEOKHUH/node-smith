# Flux (txt2img) — 권장 구조

Black Forest Labs의 guidance-distilled 확산 모델. **KSampler의 cfg는 항상 1.0**이고,
가이던스는 별도 `FluxGuidance`(또는 `CLIPTextEncodeFlux` 내장)로 준다. 세 변형:

- **Flux.1 Dev SRPO** — `DualCLIPLoader`(T5XXL + CLIP-L). **BF16 전용**(FP8은 깨짐).
- **Flux 2 Klein 9B** — 단일 `CLIPLoader`(Qwen3-8B) + `flux2-vae`. 4스텝 증류.
- **Flux 2 Turbo LoRA** — Flux.1 Dev에 물려 4스텝.

## 로더

**Flux.1 Dev SRPO**

| 역할 | 노드 | 파일 |
|------|------|------|
| UNET | `UNETLoader` | `flux.1-dev-SRPO-BFL-bf16.safetensors` (BF16만) |
| CLIP | `DualCLIPLoader` **type=`flux`** | clip1=`t5xxl_fp8_e4m3fn`, clip2=`clip_l` |
| VAE | `VAELoader` | `ae.safetensors` |

**Flux 2 Klein 9B**

| 역할 | 노드 | 파일 |
|------|------|------|
| UNET | `UNETLoader` | `bigLove_klein1.safetensors` |
| CLIP | `CLIPLoader` **type=`flux`** | `qwen_3_8b_fp8mixed.safetensors` |
| VAE | `VAELoader` | `flux2-vae.safetensors` (Flux 2 전용, ae와 다름) |

## 권장 노드 체인 (Flux.1 Dev)

```
UNETLoader ─ [LoraLoaderModelOnly(Turbo)] ─────────────────────────────┐
DualCLIPLoader ─ CLIPTextEncodeFlux(clip_l+t5xxl, guidance) ─(pos) ─────┼─ KSampler(cfg=1) ─ VAEDecode ─ SaveImage
                 (또는 CLIPTextEncode ─ FluxGuidance)                    │
EmptyLatentImage / EmptySD3LatentImage ─────────────────────────────────┘
VAELoader ────────────────────────────────────────────────────────────────
```

- **가이던스가 곧 제어** — `CLIPTextEncodeFlux`는 guidance 필드 내장(별도 FluxGuidance 불필요).
  표준 `CLIPTextEncode`를 쓰면 `FluxGuidance` 노드를 따로 붙인다.

## 샘플러 / 가이던스 권장값

| 상황 | guidance | 비고 |
|------|:--------:|------|
| 짧은 프롬프트 | 3.5~4.0 | 프롬프트 밀착 |
| 길고 복잡한 프롬프트 | 1.0~1.5 | 창의적 자유도 ↑ |
| 리얼리즘 | 2.5 | 번들거림 ↓, 디테일 ↑ |

- **KSampler cfg는 언제나 1.0** (Flux 규칙). 스텝: Dev 표준 ~20~28, Turbo/Klein 증류 4스텝.

## 함정

- **Flux.1 Dev SRPO는 BF16 전용** — FP8 쓰면 결과 깨짐.
- **cfg는 KSampler가 아니라 guidance로** — KSampler cfg를 1 아닌 값으로 두면 안 됨.
- Klein은 VAE가 `flux2-vae`(Dev의 `ae`와 다름), CLIP도 Qwen3-8B(T5XXL 아님) — 혼동 금지.

> 정답지 JSON은 추후 실제 생성·검증하며 추가.
