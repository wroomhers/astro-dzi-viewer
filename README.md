# HQ Viewer - Deep Zoom Image Viewer

A Python application that converts high-resolution images (TIFF, IMG, PNG, JPG) to Deep Zoom format (DZI) and displays them with a web-based viewer. Features OpenSeadragon-based interactive viewer with annotation (bounding box) creation, editing, and comparison capabilities.

## 🚀 Features

### 📊 Image Processing
- **Multi-Format Support**: Supports TIFF, IMG, PNG, JPG format images
- **Deep Zoom (DZI)**: Fast loading and zoom by splitting large images into tiles
- **Three Backend Options**:
  - `pyvips` (Python) - Fastest and most efficient
  - `vips` (CLI) - Command line tool
  - `Pillow` - Fallback option
- **Automatic Backend Selection**: Chooses the best backend based on available tools

### 🖼️ Web Viewer
- **OpenSeadragon Based**: Smooth zoom, pan and navigation
- **Responsive Design**: Modern, dark theme
- **Navigator**: Quick navigation with mini map
- **Full Screen View**: Sidebar removed, maximum image area

### 📝 Annotation System
- **Bounding Box Drawing**: Mouse-based box drawing mode
- **Star/Object Information**:
  - Name/Catalog number
  - Type (Star, Galaxy, Nebula, Cluster, Other)
  - Apparent magnitude
  - Color/B-V value
  - Notes
- **Visual Feedback**:
  - Drawable boxes (blue border)
  - Active box highlighting (yellow border)
  - Optional label display
- **Auto-Save**: Server-side storage in JSON format

### 🔄 Comparison Mode
- **Dynamic Compare**: Works with 1 or 2 images
- **Two Viewing Modes**:
  - **Overlay**: Layer overlay with opacity control
  - **Split**: Side-by-side comparison
- **Advanced Controls**:
  - Independent scaling
  - Layer lock (pan/zoom synchronization)
  - Layer swapping
  - Keyboard shortcuts (Alt, Shift)

### 🌐 HTTP Server
- **Built-in Server**: Integrated HTTP server
- **API Endpoints**: Save/load annotation data
- **Static File Serving**: Serves HTML, CSS, JS and tile files

## 📦 Installation

### Requirements
```bash
# Basic Python dependencies (built-in)
# Optional: For better performance
pip install pyvips
# or
sudo apt-get install libvips-tools  # vips CLI for Ubuntu/Debian
```

### Quick Start
```bash
# Clone the repository
git clone <repository-url>
cd nsac

# Run with single image
python src/hq_viewer.py --tiff external/your_image.tiff --serve

# Compare two images
python src/hq_viewer.py --tiff external/image1.tiff --tiff2 external/image2.tiff --serve
```

## 🛠️ Usage

### Command Line Parameters

```bash
python src/hq_viewer.py [OPTIONS]

REQUIRED:
  --tiff PATH           Main image file (TIFF/PNG/JPG)

OPTIONAL:
  --tiff2 PATH          Second image (for comparison)
  --out DIR             Output directory (default: ./output)
  --tile SIZE           Tile size (default: 256)
  --fmt FORMAT          Tile format: jpg/png (default: jpg)
  --overlap PIXELS      Tile overlap (default: 0)
  --serve               Start HTTP server and open in browser
  --port PORT           Server port (default: 8000)
  --backend BACKEND     DZI engine: auto/pyvips/pillow (default: auto)
  --overwrite           Recreate existing DZI files
  --unsafe-big          Remove Pillow MAX_IMAGE_PIXELS limit
```

### Example Usage

#### Basic Viewing
```bash
# Simple DZI creation and viewing
python src/hq_viewer.py --tiff external/hubble_image.tiff --serve
```

#### Comparison Mode
```bash
# Compare two Mars images
python src/hq_viewer.py \
  --tiff external/AEB_000002_0000_RED4_1.tiff \
  --tiff2 external/ESP_011920_1850_RED6_0.tiff \
  --serve --port 8080
```

#### Production Settings
```bash
# With high quality PNG tiles
python src/hq_viewer.py \
  --tiff external/heic0602a.tif \
  --fmt png --tile 512 --overlap 1 \
  --backend pyvips --overwrite
```

## 🖱️ Viewer Usage

### Main Viewer (viewer.html)
1. **Drawing Mode**: Click the "Drawing Mode" button
2. **Draw Box**: Hold and drag with mouse to draw a box
3. **Fill Form**: Enter information in the form that opens after drawing
4. **Save**: Save the annotation with the "Save" button
5. **Edit**: Click on existing boxes to edit them

### Controls
- **Show Boxes**: Hide/show annotation boxes
- **Show Labels**: Hide/show labels on boxes
- **Pan/Zoom**: Normal mode: Mouse drag, wheel zoom
- **Drawing Mode**: Pan/zoom disabled, box drawing active

### Comparison Mode (compare.html)
- **Overlay Mode**:
  - Top layer transparency with opacity slider
  - Layer selection with Alt/Shift + mouse
  - Independent scaling controls
- **Split Mode**: 
  - Side-by-side viewing
  - Toggle synchronized zoom/pan

## 📁 Project Structure

```
nsac/
├── src/
│   ├── hq_viewer.py          # Main application
│   ├── producer.py           # (legacy)
│   └── sunucu.py            # (legacy)
├── external/                 # Input images
│   ├── *.tiff, *.IMG, *.jpg
│   └── ...
├── src/output/              # Generated DZI files
│   ├── viewer.html          # Main viewer page
│   ├── compare.html         # Comparison page
│   ├── meta.json           # Image metadata
│   ├── *.dzi               # Deep Zoom descriptors
│   ├── *_files/            # Tile directories
│   └── annotations/        # Annotation JSON files
└── README.md
```

## 🔧 Technical Details

### DZI (Deep Zoom) Format
- **Pyramid Structure**: Tiles at multiple zoom levels
- **Tile-based Loading**: Only visible parts are loaded
- **Progressive Loading**: Low to high resolution transition

### Backend Performance
1. **pyvips**: Fastest, recommended for large files
2. **vips CLI**: Alternative to pyvips, requires system installation
3. **Pillow**: Pure Python, slow but always works

### Annotation Data Format
```json
{
  "image": "image_name",
  "boxes": [
    {
      "id": "uuid",
      "x": 100, "y": 200, "w": 50, "h": 30,
      "name": "Betelgeuse",
      "type": "Star",
      "mag": "0.42",
      "bv": "1.85",
      "notes": "Red supergiant",
      "created": "2025-01-01T12:00:00Z"
    }
  ]
}
```

## 🔗 API Endpoints

- `GET /api/annotations/{image_name}`: Get annotation data
- `POST /api/annotations/{image_name}`: Save annotation data
- `GET /{file}`: Serve static files

## 🛡️ Troubleshooting

### Common Issues

**1. "DecompressionBombError"**
```bash
# Use --unsafe-big parameter
python src/hq_viewer.py --tiff huge_image.tiff --unsafe-big
```

**2. "vips not found"**
```bash
# Ubuntu/Debian:
sudo apt-get install libvips-tools
# macOS:
brew install vips
```

**3. Performance Issues**
```bash
# pyvips installation is recommended
pip install pyvips
```

**4. Port in Use**
```bash
# Use different port
python src/hq_viewer.py --tiff image.tiff --serve --port 8001
```

## 📈 Future Features

- [ ] Multi-image comparison (2+)
- [ ] Annotation export (CSV, JSON)
- [ ] Catalog integration (Simbad, etc.)
- [ ] Photometry tools
- [ ] Batch processing
- [ ] Dockerize

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/new-feature`)
3. Commit your changes (`git commit -am 'Add new feature'`)
4. Push to the branch (`git push origin feature/new-feature`)
5. Create a Pull Request

## 📄 License

This project is licensed under the MIT License.

## 📞 Contact

You can open issues or submit pull requests for questions.

---

**Note**: This tool is specifically developed for astronomy images (Hubble, Mars rovers, etc.), but can work with any high-resolution image.
