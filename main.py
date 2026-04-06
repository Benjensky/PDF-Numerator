import sys
import os
import re
import json
import fitz
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QPushButton, QFileDialog, QLabel, 
    QVBoxLayout, QHBoxLayout, QWidget, QScrollArea, QTableWidget, 
    QTableWidgetItem, QHeaderView, QComboBox, QMessageBox, QSplitter,
    QFrame, QDialog, QSplitterHandle
)
from PyQt6.QtGui import QPixmap, QImage, QPainter, QColor, QPen
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QIcon
# Icône d'application
class PDFApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(self.tr_get("window_title"))
        # Ajoute cette ligne pour définir l'icône de la fenêtre
        self.setWindowIcon(QIcon("icon.svg"))

# --- LOCALISATIONS ---
def resource_path(relative_path):
    """ Pour trouver les ressources (JSON) même après compilation """
    try:
        # PyInstaller crée un dossier temporaire _MEIPASS
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)

# --- CONVERTISSEURS ---
def to_roman(n, lower=True):
    if n <= 0: return str(n)
    val = [1000, 900, 500, 400, 100, 90, 50, 40, 10, 9, 5, 4, 1]
    syb = ["M", "CM", "D", "CD", "C", "XC", "L", "XL", "X", "IX", "V", "IV", "I"]
    roman = ""
    for i in range(len(val)):
        while n >= val[i]: roman += syb[i]; n -= val[i]
    return roman.lower() if lower else roman

def to_alpha(n, lower=True):
    if n <= 0: return str(n)
    string = ""
    while n > 0:
        n, remainder = divmod(n - 1, 26)
        string = chr(65 + remainder) + string
    return string.lower() if lower else string

# --- INTERFACE ---
class CustomHandle(QSplitterHandle):
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#f0f0f0"))
        painter.setPen(QPen(QColor("#888"), 1))
        cx, cy = self.width() // 2, self.height() // 2
        for offset in [-3, 0, 3]: painter.drawLine(cx - 4, cy + offset, cx + 4, cy + offset)

class GripSplitter(QSplitter):
    def createHandle(self): return CustomHandle(self.orientation(), self)

class ZoomDialog(QDialog):
    def __init__(self, pixmap, titre, parent=None):
        super().__init__(parent)
        self.setWindowTitle(titre)
        lay = QVBoxLayout(self)
        sc = QScrollArea()
        sc.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lb = QLabel(); lb.setPixmap(pixmap)
        sc.setWidget(lb); lay.addWidget(sc)
        self.resize(850, 950)

class MiniatureLabel(QLabel):
    def __init__(self, pixmap_original, label_reference, parent_app):
        super().__init__()
        self.pixmap_original = pixmap_original
        self.label_reference = label_reference
        self.parent_app = parent_app
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setStyleSheet("border: 1px solid #bbb; background: white;")
        self.setToolTip(self.parent_app.tr_get("tooltip_zoom"))
        self.ratio = self.pixmap_original.height() / self.pixmap_original.width() if not self.pixmap_original.isNull() else 1.41
    
    def mouseDoubleClickEvent(self, event):
        texte_brut = self.label_reference.text()
        texte_propre = re.sub('<[^<]+?>', '', texte_brut)
        # Capture Y (Label X) ou Label X numérotée Y
        match = re.search(r'(.+)\s\((.+)\s(\d+)\)', texte_propre)
        if match:
            y, label_sheet, x = match.groups()
            titre = f"{self.parent_app.tr_get('zoom_title_part1')} {x} {self.parent_app.tr_get('zoom_title_part2')} {y}"
        else:
            titre = texte_propre
        ZoomDialog(self.pixmap_original, titre, self).exec()
    
    def resizeEvent(self, event):
        if not self.pixmap_original.isNull():
            w = self.width() - 4
            if w > 20:
                h = int(w * self.ratio); self.setFixedHeight(h)
                self.setPixmap(self.pixmap_original.scaled(w, h, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        super().resizeEvent(event)

class PDFApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.lang = "fr"
        self.translations = {}
        self.load_translations()
        
        self.setWindowTitle(self.tr_get("window_title"))
        self.resize(1200, 800)
        self.chemin_pdf_source = ""
        self.labels_physiques = []
        self.nb_pages_total = 0

        self.central_widget = QWidget(); self.setCentralWidget(self.central_widget)
        self.layout_fond = QVBoxLayout(self.central_widget)
        
        # --- Barre de langue améliorée ---
        self.lay_lang = QHBoxLayout()
        self.combo_lang = QComboBox()
        self.combo_lang.addItems(["Français", "English", "Español", "Deutsch"])
        self.combo_lang.currentIndexChanged.connect(self.change_language)
        self.lay_lang.addStretch(); self.lay_lang.addWidget(self.combo_lang)
        self.layout_fond.addLayout(self.lay_lang)

        self.splitter = GripSplitter(Qt.Orientation.Horizontal); self.splitter.setHandleWidth(12)

        self.zone_miniatures = QScrollArea(); self.zone_miniatures.setMinimumWidth(150)
        self.container_miniatures = QWidget(); self.layout_miniatures = QVBoxLayout(self.container_miniatures)
        self.layout_miniatures.setSpacing(10); self.layout_miniatures.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.zone_miniatures.setWidget(self.container_miniatures); self.zone_miniatures.setWidgetResizable(True)

        self.container_droite = QWidget(); self.zone_controles = QVBoxLayout(self.container_droite)
        self.btn_open = QPushButton(self.tr_get("btn_open")); self.btn_open.clicked.connect(self.ouvrir_pdf)
        self.label_nom_fichier = QLabel(self.tr_get("no_file")); self.label_nom_fichier.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        self.table_regles = QTableWidget(0, 4)
        self.table_regles.setHorizontalHeaderLabels(self.tr_get("table_headers"))
        self.table_regles.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table_regles.itemChanged.connect(self.maj_apercu_numeros)

        lay_btns = QHBoxLayout()
        self.btn_add = QPushButton(self.tr_get("btn_add")); self.btn_add.clicked.connect(lambda: self.ajouter_ligne())
        self.btn_del = QPushButton(self.tr_get("btn_del")); self.btn_del.clicked.connect(self.supprimer_ligne)
        lay_btns.addWidget(self.btn_add); lay_btns.addWidget(self.btn_del)

        self.btn_save = QPushButton(self.tr_get("btn_save"))
        self.btn_save.setStyleSheet("background-color: #4CAF50; color: white; font-weight: bold; padding: 10px;")
        self.btn_save.clicked.connect(self.enregistrer_pdf)

        self.zone_controles.addWidget(self.btn_open); self.zone_controles.addWidget(self.label_nom_fichier)
        self.zone_controles.addWidget(self.table_regles); self.zone_controles.addLayout(lay_btns); self.zone_controles.addWidget(self.btn_save)
        self.splitter.addWidget(self.zone_miniatures); self.splitter.addWidget(self.container_droite); self.splitter.setStretchFactor(1, 2)
        self.layout_fond.addWidget(self.splitter)

    def load_translations(self):
        try:
            with open(resource_path('translations.json'), 'r', encoding='utf-8') as f:
                self.translations = json.load(f)
        except Exception:
            self.translations = {"fr": {"window_title": "Erreur translations.json"}}

    def tr_get(self, key):
        return self.translations.get(self.lang, {}).get(key, key)

    def change_language(self, index):
        map_lang = {0: "fr", 1: "en", 2: "es", 3: "de"}
        self.lang = map_lang.get(index, "fr")
        
        # Mise à jour instantanée des textes
        self.setWindowTitle(self.tr_get("window_title"))
        self.btn_open.setText(self.tr_get("btn_open"))
        self.btn_add.setText(self.tr_get("btn_add"))
        self.btn_del.setText(self.tr_get("btn_del"))
        self.btn_save.setText(self.tr_get("btn_save"))
        self.table_regles.setHorizontalHeaderLabels(self.tr_get("table_headers"))
        
        if not self.chemin_pdf_source:
            self.label_nom_fichier.setText(self.tr_get("no_file"))
        else:
            nom = os.path.basename(self.chemin_pdf_source)
            self.label_nom_fichier.setText(f"{self.tr_get('file_label')} <b>{nom}</b>")
        
        # Mettre à jour les styles dans le tableau existant
        for r in range(self.table_regles.rowCount()):
            combo = self.table_regles.cellWidget(r, 1)
            if isinstance(combo, QComboBox):
                curr = combo.currentIndex()
                combo.blockSignals(True)
                combo.clear()
                combo.addItems(self.tr_get("styles"))
                combo.setCurrentIndex(curr)
                combo.blockSignals(False)

        self.maj_apercu_numeros()

    def ajouter_ligne(self, start="1", style_code="D", prefix="", first="1"):
        self.table_regles.blockSignals(True)
        row = self.table_regles.rowCount(); self.table_regles.insertRow(row)
        self.table_regles.setItem(row, 0, QTableWidgetItem(str(start)))
        combo = QComboBox()
        combo.addItems(self.tr_get("styles"))
        codes = ["D", "r", "R", "a", "A"]
        if style_code in codes: combo.setCurrentIndex(codes.index(style_code))
        combo.currentIndexChanged.connect(self.maj_apercu_numeros)
        self.table_regles.setCellWidget(row, 1, combo)
        self.table_regles.setItem(row, 2, QTableWidgetItem(str(prefix)))
        self.table_regles.setItem(row, 3, QTableWidgetItem(str(first)))
        self.table_regles.blockSignals(False); self.maj_apercu_numeros()

    def supprimer_ligne(self):
        self.table_regles.removeRow(self.table_regles.currentRow()); self.maj_apercu_numeros()

    def maj_apercu_numeros(self):
        if self.nb_pages_total == 0: return
        regles = []
        for r in range(self.table_regles.rowCount()):
            try:
                start = int(self.table_regles.item(r, 0).text()) - 1
                style = ["D", "r", "R", "a", "A"][self.table_regles.cellWidget(r, 1).currentIndex()]
                regles.append({'start': start, 'style': style, 'pref': self.table_regles.item(r, 2).text(), 'first': int(self.table_regles.item(r, 3).text())})
            except: continue
        regles.sort(key=lambda x: x['start'])

        for i in range(self.nb_pages_total):
            active_r = {'start': 0, 'style': 'D', 'pref': '', 'first': 1}
            for r in regles:
                if r['start'] <= i: active_r = r
                else: break
            val = active_r['first'] + (i - active_r['start'])
            num = str(val)
            if active_r['style'] == 'r': num = to_roman(val, True)
            elif active_r['style'] == 'R': num = to_roman(val, False)
            elif active_r['style'] == 'a': num = to_alpha(val, True)
            elif active_r['style'] == 'A': num = to_alpha(val, False)
            self.labels_physiques[i].setText(f"<b>{active_r['pref']}{num}</b> <i>({self.tr_get('sheet_label')} {i+1})</i>")

    def ouvrir_pdf(self):
        chemin, _ = QFileDialog.getOpenFileName(self, "Open/Ouvrir/Abrir/Öffnen", "", "PDF (*.pdf)")
        if chemin:
            self.chemin_pdf_source = chemin
            self.label_nom_fichier.setText(f"{self.tr_get('file_label')} <b>{os.path.basename(chemin)}</b>")
            self.charger_contenu_pdf(chemin)

    def charger_contenu_pdf(self, chemin):
        for i in reversed(range(self.layout_miniatures.count())):
            w = self.layout_miniatures.itemAt(i).widget()
            if w: w.setParent(None)
        self.table_regles.setRowCount(0); self.labels_physiques = []; doc = fitz.open(chemin); self.nb_pages_total = len(doc)
        for i in range(self.nb_pages_total):
            pix = doc[i].get_pixmap(matrix=fitz.Matrix(1.5, 1.5))
            qimg = QImage(pix.samples, pix.width, pix.height, pix.stride, QImage.Format.Format_RGB888)
            container = QWidget(); lay = QVBoxLayout(container); lbl_num = QLabel(); lbl_num.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.labels_physiques.append(lbl_num); lbl_img = MiniatureLabel(QPixmap.fromImage(qimg), lbl_num, self)
            lay.addWidget(lbl_num); lay.addWidget(lbl_img); self.layout_miniatures.addWidget(container)
            if i < self.nb_pages_total-1:
                f = QFrame(); f.setFrameShape(QFrame.Shape.HLine); f.setStyleSheet("color: #ddd; margin: 0 20px;"); self.layout_miniatures.addWidget(f)
        for label in doc.get_page_labels(): self.ajouter_ligne(label['startpage']+1, label.get('style','D'), label.get('prefix',''), label.get('firstpagenum',1))
        doc.close(); self.maj_apercu_numeros()

    def enregistrer_pdf(self):
        if not self.chemin_pdf_source: return
        dest, _ = QFileDialog.getSaveFileName(self, self.tr_get("btn_save"), "output.pdf", "PDF (*.pdf)")
        if not dest: return
        try:
            doc = fitz.open(self.chemin_pdf_source); labels = []
            for r in range(self.table_regles.rowCount()):
                labels.append({"startpage": int(self.table_regles.item(r,0).text())-1, "style": ["D","r","R","a","A"][self.table_regles.cellWidget(r,1).currentIndex()], "prefix": self.table_regles.item(r,2).text(), "firstpagenum": int(self.table_regles.item(r,3).text())})
            labels.sort(key=lambda x: x["startpage"]); doc.set_page_labels(labels); doc.save(dest); doc.close()
            QMessageBox.information(self, self.tr_get("msg_success"), self.tr_get("msg_success"))
        except Exception as e:
            msg = self.tr_get("msg_file_used") if "save to original" in str(e) else f"{self.tr_get('msg_error')}: {e}"
            QMessageBox.critical(self, self.tr_get("msg_error"), msg)

if __name__ == "__main__":
    app = QApplication(sys.argv); window = PDFApp(); window.show(); sys.exit(app.exec())
