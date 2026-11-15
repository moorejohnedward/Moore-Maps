"""Makes a simple test picture (two bright blobs and a dark band) for the build check."""
import sys

import numpy as np
from PIL import Image

out = sys.argv[1] if len(sys.argv) > 1 else "sample.png"
y, x = np.mgrid[0:600, 0:800] / 600.0
img = (0.9 * np.exp(-((x - 0.45) ** 2 + (y - 0.35) ** 2) / 0.03)
       + 0.7 * np.exp(-((x - 0.95) ** 2 + (y - 0.65) ** 2) / 0.02)
       + 0.25 * np.sin(9 * x) * np.cos(7 * y) + 0.3)
img = np.clip(img / img.max(), 0, 1)
Image.fromarray((img * 255).astype(np.uint8)).convert("RGB").save(out)
print("wrote", out)
