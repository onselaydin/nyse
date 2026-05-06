from __future__ import annotations

from pathlib import Path

import torch
import torch.nn as nn
from torch.utils.data import DataLoader
from torchvision import datasets, transforms

from ai.cnn_model import CandleCNN
from config import get_config
from core.logger import setup_logger


def train() -> None:
    cfg = get_config()
    logger = setup_logger(cfg.paths.logs_dir)

    dataset_dir = cfg.paths.dataset_dir
    model_out = cfg.paths.ai_models_dir / "candle_cnn.pt"
    model_out.parent.mkdir(parents=True, exist_ok=True)

    device = torch.device("cuda" if (cfg.ai.use_cuda_if_available and torch.cuda.is_available()) else "cpu")
    logger.info("AI eğitim cihazı: %s", device)

    transform = transforms.Compose(
        [
            transforms.Resize((cfg.ai.image_size, cfg.ai.image_size)),
            transforms.ToTensor(),
        ]
    )

    if not dataset_dir.exists():
        logger.error("Dataset klasörü bulunamadı: %s", dataset_dir)
        return

    dataset = datasets.ImageFolder(root=str(dataset_dir), transform=transform)
    if len(dataset) == 0:
        logger.error("Dataset boş. Önce dataset üretin.")
        return

    train_loader = DataLoader(dataset, batch_size=cfg.ai.batch_size, shuffle=True, num_workers=0)

    model = CandleCNN(num_classes=len(dataset.classes)).to(device)
    criterion = nn.CrossEntropyLoss()
    optimizer = torch.optim.Adam(model.parameters(), lr=cfg.ai.learning_rate)

    model.train()
    for epoch in range(cfg.ai.epochs):
        running_loss = 0.0
        correct = 0
        total = 0

        for images, labels in train_loader:
            images = images.to(device)
            labels = labels.to(device)

            optimizer.zero_grad()
            outputs = model(images)
            loss = criterion(outputs, labels)
            loss.backward()
            optimizer.step()

            running_loss += float(loss.item()) * images.size(0)
            _, pred = torch.max(outputs, dim=1)
            correct += int((pred == labels).sum().item())
            total += int(labels.size(0))

        epoch_loss = running_loss / max(1, total)
        epoch_acc = (correct / max(1, total)) * 100.0
        logger.info("Epoch %s/%s | Loss=%.5f | Acc=%.2f%%", epoch + 1, cfg.ai.epochs, epoch_loss, epoch_acc)

    torch.save(model.state_dict(), model_out)
    logger.info("Model kaydedildi: %s", model_out)


if __name__ == "__main__":
    train()
