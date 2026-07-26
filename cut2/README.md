# cut2 - A Smarter `cut`

`cut2` is an enhanced version of `cut` that **correctly handles quoted fields**, **escaped delimiters**, and **embedded spaces**.

## 🚀 Features
- **Full `cut` replacement**: Supports `-f` (fields) and `-c` (characters)
- **Handles quoted fields correctly**: `"foo bar"` is treated as one field
- **Supports custom delimiters (`-d`)**: Works with spaces, commas, tabs, etc.
- **Works on Linux, BSD, macOS, and Cygwin**
- **Debian (`.deb`) and RPM (`.rpm`) packages available**

## 📦 Installation

### **Linux/macOS (Manual)**
```bash
git clone https://github.com/yourname/cut2.git
cd cut2
./configure
make
sudo make install
