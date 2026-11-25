"""Auswertung des LandXML-Exports aus Civil 3D (ID 64, Kanalnetz).

Liest Schaechte (Structs), Haltungen (Pipes), die Achse Achse_Kanal und den
Gelaendelaengsschnitt aus data/ID64_Kanalnetz.xml. Erzeugt eine Schacht- und
Haltungsliste, prueft Gefaelle, Ueberdeckung und Absturzhoehen, schaetzt die
Vollfuellungsleistung (Manning-Strickler) und erzeugt zwei Grafiken.
"""
from pathlib import Path
import math
import re
import xml.etree.ElementTree as ET

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parents[1]
XML = ROOT / "data" / "ID64_Kanalnetz.xml"
RES = ROOT / "results"
IMG = ROOT / "images"
NS = {"l": "http://www.landxml.org/schema/LandXML-1.2"}
KST = 85.0                 # Strickler-Beiwert kSt fuer PVC (m^(1/3)/s), vereinfacht
MIN_COVER = 1.0            # Mindestueberdeckung (m), Frostschutz
X0 = 366150.0              # Rechtswert des ersten Schachts = Station 0+000


def short(name):
    m = re.search(r"\((\d+)\)", name)
    return m.group(1) if m else name


def main():
    RES.mkdir(exist_ok=True)
    IMG.mkdir(exist_ok=True)
    root = ET.parse(XML).getroot()
    net = root.find(".//l:PipeNetwork", NS)

    st = {}
    for s in net.findall("l:Structs/l:Struct", NS):
        n, e = (float(v) for v in s.find("l:Center", NS).text.split()[:2])
        inv = {"in": None, "out": None}
        for i in s.findall("l:Invert", NS):
            inv[i.get("flowDir")] = float(i.get("elev"))
        st[s.get("name")] = {"Schacht": "S" + short(s.get("name")), "E": e, "N": n,
                             "Deckel_m": float(s.get("elevRim")), "Sohle_m": float(s.get("elevSump")),
                             "DN_Schacht_mm": float(s.find("l:CircStruct", NS).get("diameter")),
                             "Zulauf_m": inv["in"], "Ablauf_m": inv["out"]}
    sch = pd.DataFrame(st.values()).sort_values("E").reset_index(drop=True)
    sch["Station_m"] = (sch["E"] - X0).round(2)
    sch["Schachttiefe_m"] = (sch["Deckel_m"] - sch["Sohle_m"]).round(2)
    sch["Absturz_m"] = (sch["Zulauf_m"] - sch["Ablauf_m"]).round(3)

    rows = []
    for p in net.findall("l:Pipes/l:Pipe", NS):
        a, b = st[p.get("refStart")], st[p.get("refEnd")]
        d = float(p.find("l:CircPipe", NS).get("diameter")) / 1000
        za, ze = a["Ablauf_m"], b["Zulauf_m"]
        length = float(p.get("length"))
        slope = float(p.get("slope"))
        area, rh = math.pi * d ** 2 / 4, d / 4
        v = KST * rh ** (2 / 3) * math.sqrt(slope)
        rows.append({"Haltung": "H" + short(p.get("name")), "von": a["Schacht"], "nach": b["Schacht"],
                     "DN_mm": d * 1000, "Material": p.find("l:CircPipe", NS).get("material"),
                     "Laenge_m": round(length, 2), "Gefaelle_%": round(slope * 100, 2),
                     "Sohle_oben_m": round(za, 3), "Sohle_unten_m": round(ze, 3),
                     "Ueberdeckung_oben_m": round(a["Deckel_m"] - za - d, 2),
                     "Ueberdeckung_unten_m": round(b["Deckel_m"] - ze - d, 2),
                     "v_voll_m_s": round(v, 2), "Q_voll_l_s": round(v * area * 1000, 1)})
    hal = pd.DataFrame(rows).sort_values("Sohle_oben_m", ascending=False).reset_index(drop=True)
    hal["Min_Gefaelle_ok"] = hal["Gefaelle_%"] >= 100 / hal["DN_mm"]          # Faustregel 1:DN
    hal["Ueberdeckung_ok"] = hal[["Ueberdeckung_oben_m", "Ueberdeckung_unten_m"]].min(axis=1) >= MIN_COVER

    al = root.find(".//l:Alignment", NS)
    gnd = np.array([float(v) for v in al.find(".//l:ProfSurf/l:PntList2D", NS).text.split()]).reshape(-1, 2)

    kpi = [
        ("Netz / Typ", f"{net.get('name')} / Freispiegelkanal (Teilesatz Sanitary Sewer)"),
        ("Schaechte / Haltungen", f"{len(sch)} / {len(hal)}"),
        ("Gesamtlaenge Haltungen (m)", round(hal["Laenge_m"].sum(), 1)),
        ("Rohr", f"DN {hal['DN_mm'].iloc[0]:.0f} {hal['Material'].iloc[0]}, "
                 f"Schacht DN {sch['DN_Schacht_mm'].iloc[0]:.0f}"),
        ("Achse Achse_Kanal (m)", round(float(al.get("length")), 2)),
        ("Deckelhoehe max / min (m)", f"{sch['Deckel_m'].max():.2f} / {sch['Deckel_m'].min():.2f}"),
        ("Sohle Anfang / Ende (m)", f"{sch['Ablauf_m'].iloc[0]:.2f} / {sch['Zulauf_m'].iloc[-1]:.2f}"),
        ("Gefaelle min / max (%)", f"{hal['Gefaelle_%'].min():.2f} / {hal['Gefaelle_%'].max():.2f}"),
        ("Schachttiefe min / max (m)", f"{sch['Schachttiefe_m'].min():.2f} / {sch['Schachttiefe_m'].max():.2f}"),
        ("Ueberdeckung min / max (m)",
         f"{hal[['Ueberdeckung_oben_m', 'Ueberdeckung_unten_m']].min().min():.2f} / "
         f"{hal[['Ueberdeckung_oben_m', 'Ueberdeckung_unten_m']].max().max():.2f}"),
        ("max. Absturz im Schacht (m)",
         f"{sch['Absturz_m'].max():.2f} ({sch.loc[sch['Absturz_m'].idxmax(), 'Schacht']})"),
        ("Vollfuellung Q min / max (l/s)", f"{hal['Q_voll_l_s'].min():.0f} / {hal['Q_voll_l_s'].max():.0f}"),
        ("Pruefung Mindestgefaelle 1:DN", "alle ok" if hal["Min_Gefaelle_ok"].all() else "nicht alle ok"),
        ("Pruefung Ueberdeckung >= 1,0 m", "alle ok" if hal["Ueberdeckung_ok"].all() else "nicht alle ok"),
    ]
    kp = pd.DataFrame(kpi, columns=["Kennzahl", "Wert"])
    kp.to_csv(RES / "kennzahlen.csv", index=False, sep=";")
    sch.to_csv(RES / "schachtliste.csv", index=False, sep=";", decimal=",")
    hal.to_csv(RES / "haltungsliste.csv", index=False, sep=";", decimal=",")
    with pd.ExcelWriter(RES / "civil3d_kanalnetz.xlsx") as xw:
        kp.to_excel(xw, sheet_name="Kennzahlen", index=False)
        sch.to_excel(xw, sheet_name="Schaechte", index=False)
        hal.to_excel(xw, sheet_name="Haltungen", index=False)

    # Grafik 1: Laengsschnitt aus LandXML
    fig, ax = plt.subplots(figsize=(12, 5.4))
    ax.plot(gnd[:, 0], gnd[:, 1], color="#8b5a2b", lw=1.6, label="Gelände DGM_Bestand")
    for _, r in hal.iterrows():
        a = sch[sch.Schacht == r["von"]].iloc[0]
        b = sch[sch.Schacht == r["nach"]].iloc[0]
        xs = [a["Station_m"], b["Station_m"]]
        ax.plot(xs, [r["Sohle_oben_m"], r["Sohle_unten_m"]], color="#7d3c98", lw=2.2)
        ax.plot(xs, [r["Sohle_oben_m"] + 0.3, r["Sohle_unten_m"] + 0.3], color="#7d3c98", lw=1)
        ax.text(sum(xs) / 2, (r["Sohle_oben_m"] + r["Sohle_unten_m"]) / 2 - 0.9,
                f"{r['Haltung']}\n{r['Gefaelle_%']:.2f} %", ha="center", fontsize=8, color="#7d3c98")
    for _, s in sch.iterrows():
        ax.plot([s["Station_m"]] * 2, [s["Sohle_m"], s["Deckel_m"]], color="#1f3864", lw=3)
        ax.text(s["Station_m"], s["Deckel_m"] + 0.4, s["Schacht"], ha="center", fontsize=9, color="#1f3864")
    ax.plot([], [], color="#7d3c98", lw=2.2, label="Haltung DN 300 (Sohle / Scheitel)")
    ax.plot([], [], color="#1f3864", lw=3, label="Schacht DN 1500")
    ax.set_xlabel("Station (m)")
    ax.set_ylabel("Höhe (m NHN)")
    ax.set_title("Kanal_SW – Längsschnitt aus LandXML (Civil 3D 2027)")
    ax.grid(alpha=.3)
    ax.legend(loc="upper right", fontsize=9)
    fig.tight_layout()
    fig.savefig(IMG / "05_Laengsschnitt_LandXML.png", dpi=150)
    plt.close(fig)

    # Grafik 2: Schachttiefe, Ueberdeckung, Gefaelle
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(12, 4.8))
    a1.bar(sch["Schacht"], sch["Schachttiefe_m"], color="#2e86c1")
    for i, v in enumerate(sch["Schachttiefe_m"]):
        a1.text(i, v + 0.1, f"{v:.2f}", ha="center", fontsize=8)
    a1.set_title("Schachttiefe Deckel − Sohle (m)")
    a1.grid(axis="y", alpha=.3)
    x = np.arange(len(hal))
    a2.bar(x - 0.2, hal["Ueberdeckung_oben_m"], 0.4, color="#27ae60", label="Überdeckung oben (m)")
    a2.bar(x + 0.2, hal["Ueberdeckung_unten_m"], 0.4, color="#82e0aa", label="Überdeckung unten (m)")
    a2.axhline(MIN_COVER, color="#c0392b", ls="--", lw=1, label="Mindestüberdeckung 1,0 m")
    a2.set_xticks(x, [f"{h}\n{g:.2f} %" for h, g in zip(hal["Haltung"], hal["Gefaelle_%"])])
    a2.set_title("Überdeckung je Haltung (mit Gefälle)")
    a2.legend(fontsize=8, loc="upper right")
    a2.grid(axis="y", alpha=.3)
    fig.tight_layout()
    fig.savefig(IMG / "06_Schaechte_Haltungen_LandXML.png", dpi=150)
    plt.close(fig)
    print(kp.to_string(index=False))
    print(sch.to_string(index=False))
    print(hal.to_string(index=False))


if __name__ == "__main__":
    main()
