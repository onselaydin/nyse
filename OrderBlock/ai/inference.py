from __future__ import annotations

from pathlib import Path
from typing import Sequence

import numpy as np
import torch
from PIL import Image
from torchvision import transforms

from ai.cnn_model import CandleCNN
from config import AppConfig


class AIInference:
    def __init__(self, cfg: AppConfig, logger):
        self.cfg = cfg
        self.logger = logger
        self.device = torch.device("cuda" if (cfg.ai.use_cuda_if_available and torch.cuda.is_available()) else "cpu")
        self.labels = list(cfg.ai.labels)

        self.model = CandleCNN(num_classes=len(self.labels)).to(self.device)
        self.model.eval()

        self.transform = transforms.Compose(
            [
                transforms.Resize((cfg.ai.image_size, cfg.ai.image_size)),
                transforms.ToTensor(),
            ]
        )

    def load_weights(self, model_path: Path) -> None:
        if not model_path.exists():
            self.logger.warning("AI model dosyası bulunamadı: %s", model_path)
            return
        state = torch.load(model_path, map_location=self.device)
        self.model.load_state_dict(state)
        self.model.eval()
        self.logger.info("AI model yüklendi: %s", model_path)

    def predict_image(self, image_path: Path) -> tuple[str, float]:
        image = Image.open(image_path).convert("RGB")
        x = self.transform(image).unsqueeze(0).to(self.device)

        with torch.no_grad():
            logits = self.model(x)
            probs = torch.softmax(logits, dim=1).squeeze(0).cpu().numpy()

        idx = int(np.argmax(probs))
        return self.labels[idx], float(probs[idx])

    def predict_feature_vector(self, features: Sequence[float]) -> tuple[str, float]:
        arr = np.asarray(features, dtype=np.float32)
        score = float(np.tanh(np.mean(arr) * 1e-4))
        if score > 0.15:
            return "high_probability_setup", min(0.95, 0.5 + score)
        if score < -0.15:
            return "bad_setup", min(0.95, 0.5 + abs(score))
        return "momentum_candle", 0.55
