"""Entrena E1 o E2 con el SFTTrainer de TRL y LoRA, según src/fase5/experimento.yaml.

Uso, desde la raíz del repositorio (después de las fases 4 y 5), con las dependencias de
requirements-entrenamiento.txt:
    python -m src.fase5.entrenar --prueba                    # CPU, modelo diminuto, 2 pasos: comprueba el flujo
    python -m src.fase5.entrenar --experimento E1 --salida runs/E1      # en una GPU
    python -m src.fase5.entrenar --experimento E2 --salida runs/E2

Lee data/fase4/sft/{train,validation}.jsonl: formato conversacional con herramientas
(`messages` + `tools`) y `chat_template_kwargs` = {"enable_thinking": false} por fila.

Cómo se resuelve cada punto delicado (comprobado con --prueba y en src/tests/test_fase5.py):
- Máscara de pérdida: `assistant_only_loss=True`. La plantilla de Qwen3.5 no tiene marcas
  {% generation %}; TRL la reconoce y usa su plantilla de entrenamiento (qwen3_5_think_training),
  que supervisa los turnos del asistente, incluido su <|im_end|>, y nada más.
- Longitud: `max_length` vale 1024 por defecto en TRL y cortaría casi todas las conversaciones
  (y con ellas la respuesta, que va al final). Se fija en 24.576.
- Presupuesto: `max_steps` sale de la fase 5, para que E1 y E2 den los mismos pasos.
- LoRA solo en el modelo de lenguaje: el encoder de visión queda congelado.

No se ha ejecutado un entrenamiento real (no hay GPU en este entorno): --prueba solo valida el flujo.
"""

from __future__ import annotations

import argparse
import math
import re
import sys
from pathlib import Path

from src.fase0.label import ROOT, read_jsonl
from src.fase4.run import FASE4, SFT_DIR
from src.fase5.run import load_config, presupuesto

MODELO_PRUEBA = "trl-internal-testing/tiny-Qwen3_5ForConditionalGeneration-Think"
REVISION_PRUEBA = "6860d7ec861ade2fe4e44dc69bf57064fdc82b12"   # misma plantilla y vocabulario que Qwen3.5-4B


def lora_targets(lora: dict) -> str:
    """Expresión regular de PEFT: los módulos de experimento.yaml, solo dentro del modelo de lenguaje.
    Así quedan fuera los del encoder de visión (model.visual.*), que tienen nombres parecidos."""
    return re.escape(lora["alcance"]) + r"\..*\.(" + "|".join(lora["modulos"]) + ")"


def datasets_sft(excluidas: list[str], prueba: bool):
    from datasets import load_dataset
    train = load_dataset("json", data_files=str(SFT_DIR / "train.jsonl"), split="train")
    val = load_dataset("json", data_files=str(SFT_DIR / "validation.jsonl"), split="train")
    train = train.filter(lambda r: r["situacion"] not in excluidas)
    if prueba:
        # Las conversaciones más cortas, incluida una con historial, para que quepa en CPU.
        tokens = {r["id"]: r["tokens"] for r in read_jsonl(FASE4 / "train.jsonl") + read_jsonl(FASE4 / "validation.jsonl")}
        cortas = sorted(train, key=lambda r: tokens[r["id"]])
        hist = next(r["id"] for r in cortas if r["situacion"] == "software_en_historial")
        ids = {r["id"] for r in cortas[:3]} | {hist}
        train = train.filter(lambda r: r["id"] in ids)
        val = val.filter(lambda r: r["id"] in {r["id"] for r in sorted(val, key=lambda r: tokens[r["id"]])[:2]})
    return train, val


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--experimento", choices=["E1", "E2"], default="E1")
    p.add_argument("--salida", default=None, help="carpeta de los checkpoints (por defecto runs/<experimento>)")
    p.add_argument("--prueba", action="store_true", help="CPU, modelo diminuto y 2 pasos: comprueba el flujo")
    args = p.parse_args()

    import torch
    from peft import LoraConfig
    from transformers import AutoModelForImageTextToText, AutoTokenizer
    from trl import SFTConfig, SFTTrainer

    cfg = load_config()
    t, m = cfg["entrenamiento"], cfg["modelo"]
    exp = cfg["experimentos"][args.experimento]["entrenamiento"]
    budget = presupuesto(cfg, read_jsonl(FASE4 / "train.jsonl"))[args.experimento]
    batch = t["batch_por_dispositivo"] * t["acumulacion_gradiente"]
    pasos_por_epoca = math.ceil(budget["conversaciones"] / batch)

    model_id, revision = (MODELO_PRUEBA, REVISION_PRUEBA) if args.prueba else (m["id"], m["revision"])
    salida = args.salida or str(ROOT / "runs" / ("prueba" if args.prueba else args.experimento))
    train, val = datasets_sft(exp["situaciones_excluidas"], args.prueba)

    tok = AutoTokenizer.from_pretrained(model_id, revision=revision)
    model = AutoModelForImageTextToText.from_pretrained(
        model_id, revision=revision, dtype=torch.float32 if args.prueba else torch.bfloat16)
    lora = t["lora"]
    peft_config = LoraConfig(r=lora["r"], lora_alpha=lora["alpha"], lora_dropout=lora["dropout"],
                             target_modules=lora_targets(lora), task_type="CAUSAL_LM")
    sft = SFTConfig(
        output_dir=salida,
        assistant_only_loss=True,
        max_length=t["longitud_maxima"],
        packing=t["packing"],
        per_device_train_batch_size=t["batch_por_dispositivo"],
        per_device_eval_batch_size=1,
        gradient_accumulation_steps=2 if args.prueba else t["acumulacion_gradiente"],
        max_steps=2 if args.prueba else budget["pasos"],
        learning_rate=t["tasa_aprendizaje"],
        lr_scheduler_type=t["programa"],
        warmup_steps=t["warmup"],
        weight_decay=t["weight_decay"],
        bf16=not args.prueba and t["precision"] == "bf16",
        gradient_checkpointing=not args.prueba and t["gradient_checkpointing"],
        seed=t["semilla"],
        # Un checkpoint y una evaluación en validation al final de cada época (fase 5, selección).
        eval_strategy="steps", eval_steps=1 if args.prueba else pasos_por_epoca,
        save_strategy="steps", save_steps=2 if args.prueba else pasos_por_epoca,
        logging_steps=1, report_to="none",
        use_cpu=args.prueba,             # en un Mac, si no, usaría la GPU (MPS) y se queda sin memoria
    )
    trainer = SFTTrainer(model=model, args=sft, train_dataset=train, eval_dataset=val,
                         processing_class=tok, peft_config=peft_config)

    # Qué se va a supervisar en la primera conversación: debe ser solo la llamada y la respuesta.
    ex = trainer.train_dataset[0]
    mask = ex.get("assistant_masks") or [int(l != -100) for l in ex["labels"]]
    supervisado = tok.decode([i for i, k in zip(ex["input_ids"], mask) if k])
    print(f"Modelo: {model_id} · experimento {args.experimento} · {len(train)} conversaciones · "
          f"{sft.max_steps} pasos · longitud máxima {sft.max_length}")
    print(f"Primera conversación: {len(ex['input_ids'])} tokens, {sum(mask)} supervisados:\n{supervisado[:600]}")
    trainable = sum(p.numel() for p in trainer.model.parameters() if p.requires_grad)
    print(f"Parámetros entrenables (LoRA): {trainable}")

    result = trainer.train()
    print(f"Entrenamiento terminado: pérdida {result.training_loss:.4f} · checkpoints en {salida}")
    return 0 if math.isfinite(result.training_loss) else 1


if __name__ == "__main__":
    sys.exit(main())
