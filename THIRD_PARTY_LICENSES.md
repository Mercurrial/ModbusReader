# Third-party components

ModbusReader itself is licensed under the GNU General Public License,
version 3 or (at your option) any later version — see [LICENSE](LICENSE).

The builds (`ModbusReader.exe`, the installer) bundle the components below.
Each keeps its own licence; the full texts come with each package (see its
project page or the `*.dist-info/licenses` folder of the installed package).

| Component | Licence | Project |
|---|---|---|
| PyQt6 | GPL-3.0-only | https://www.riverbankcomputing.com/software/pyqt/ |
| Qt 6 (PyQt6-Qt6) | LGPL-3.0 | https://www.qt.io/ |
| PyQt6-sip | BSD-2-Clause | https://www.riverbankcomputing.com/software/sip/ |
| pyqtgraph | MIT | https://www.pyqtgraph.org/ |
| pyserial | BSD-3-Clause | https://github.com/pyserial/pyserial |
| NumPy | BSD-3-Clause (and the licences of its bundled libraries) | https://numpy.org/ |
| openpyxl | MIT | https://openpyxl.readthedocs.io/ |
| et-xmlfile | MIT | https://foss.heptapod.net/openpyxl/et_xmlfile |
| Python | PSF License | https://www.python.org/ |
| PyInstaller bootloader | GPL-2.0-or-later with the bootloader exception | https://pyinstaller.org/ |

The Qt libraries are shipped as separate files in the installed copy
(`_internal` folder) and may be replaced by compatible builds, as the LGPL
allows. Their source code is available from https://download.qt.io/.

The installer is built with Inno Setup (https://jrsoftware.org/isinfo.php).
