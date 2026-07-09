# LTX-V2 (19B) 영상 — 권장 구조

Lightricks의 19B DiT 영상 모델. **Gemma 3 12B** 텍스트 인코더를 쓰고 T2V·I2V 모두 지원.

- **증류 모델**로 8스텝 빠른 생성
- **2단계 파이프라인**: 저해상도 생성 → latent 공간에서 2배 업스케일
- 카메라 컨트롤 LoRA(시네마틱 무빙), 오디오-비디오 동시 생성(옵션)

## 로더

| 역할 | 노드 | 파일 |
|------|------|------|
| 체크포인트(VAE 내장) | `CheckpointLoaderSimple` | `ltx-2-19b-distilled.safetensors` (41GB bf16) |
| 텍스트(Gemma 3) | `CLIPLoader` **type=`ltxv`** | `gemma_3_12B_it_fp4_mixed.safetensors` (text_encoders/) |

> 체크포인트가 VAE를 품고 있어 별도 VAELoader 불필요. Gemma 3만 따로 로드.

## 핵심 노드

- **`LTXVConditioning`** — 텍스트 조건 + frame_rate를 묶음(pos/neg, frame_rate 예: 25).
- **`EmptyLTXVLatentVideo`** — T2V용 초기 latent(width/height/length, 예: 768×512×97).
- **증류 LoRA** `ltx-2-19b-distilled-lora-384` — 베이스에 물려 증류 동작. 카메라 컨트롤 LoRA로 무빙.

## 권장 노드 체인 (T2V, 증류 8-step)

```
CheckpointLoaderSimple ─ [Distilled/Camera LoRA] ─┐
CLIPLoader(ltxv) ─ CLIPTextEncode(pos)/(neg) ─ LTXVConditioning(frame_rate) ─┼─ KSampler ─ VAEDecode ─ (영상)
EmptyLTXVLatentVideo(width,height,length) ─────────────────────────────────┘
```

I2V면 시작 이미지를 인코딩해 latent 초기화에 넣는다(EmptyLTXVLatentVideo 대신 이미지 기반 latent).

## 샘플러 / 2단계

- **증류**: 8스텝 빠른 생성.
- **2단계 업스케일**: 1단계 저해상도 → latent 2배 공간 업스케일 후 재디노이즈(선명도↑).

## 함정

- `CLIPLoader` type=`ltxv`, Gemma 3 인코더(다른 계열 인코더와 혼동 금지).
- 체크포인트에 VAE 내장 → **별도 VAELoader 붙이면 중복**.
- 41GB 모델 — VRAM 큼. 저해상도 생성 후 업스케일 전략 권장.

> 정답지 JSON은 추후 실제 생성·검증하며 추가.
