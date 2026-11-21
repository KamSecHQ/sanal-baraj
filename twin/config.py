"""Dijital ikizin varsayılan parametreleri.

Buradaki her sayı bir varsayımdır; su mühendisi gözden geçirip gerekirse değiştirmeli.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
REF_DIR = DATA_DIR / "ref"
CACHE_DIR = DATA_DIR / "cache"

# --- Borular ---------------------------------------------------------------
# Ticari boru çapları (mm). Boyutlandırma bu listede bir üst çapa çıkar.
PIPE_SIZES_MM = [100, 150, 200, 250, 300, 400, 500, 600]
# Yol sınıfına göre başlangıç çapı. İstanbul kesintilerinin çoğu 100 mm hatlarda.
HIGHWAY_DIAMETER_MM = {"trunk": 300, "primary": 300, "secondary": 200, "tertiary": 150}
DEFAULT_DIAMETER_MM = 100
# Bu yolların altından dağıtım borusu geçtiğini varsaymıyoruz.
EXCLUDED_HIGHWAYS = {"motorway", "motorway_link", "trunk_link"}
# Liste halinde gelen highway etiketinde öncelik sırası
HIGHWAY_PRIORITY = [
    "trunk", "primary", "secondary", "tertiary", "unclassified",
    "residential", "living_street", "service", "road",
]
HAZEN_WILLIAMS_C = 130.0

# Boyutlandırma ölçütleri (tepe saatte)
MAX_VELOCITY_MS = 1.5
MAX_HEADLOSS_M_PER_KM = 7.0
SIZING_ITERATIONS = 8

# Şebeke durumu: "tasarim" yeni ve cömert boyutlu bir şebeke, "mevcut" yaşlanmış ve
# pürüzlenmiş borulu, tepe saatte daha çok yük kaybı yaşayan bir şebeke.
NETWORK_STATES = {
    "tasarim": {"roughness": 130.0, "max_velocity": 1.5, "max_headloss": 7.0},
    "mevcut": {"roughness": 100.0, "max_velocity": 2.0, "max_headloss": 15.0},
}

# --- Basınç ---------------------------------------------------------------
# Her DMA'nın girişi, kritik düğüm tepe saatte bu basıncı görecek şekilde ayarlanır.
TARGET_CRITICAL_PRESSURE_M = 22.0
MIN_SERVICE_PRESSURE_M = 15.0

# --- DMA (izole ölçüm bölgesi) ------------------------------------------------
NODES_PER_DMA = 400
# Kümelemede 1 m kot farkı kaç metre yatay mesafeye denk sayılsın
ELEV_WEIGHT = 30.0
# Bir DMA içinde izin verilen en büyük kot farkı. Kritik düğüm ~22 m aldığında
# en alçak düğüm ~22 + 35 ≈ 57 m (5,7 bar) statik basınç görür.
MAX_DMA_ELEV_SPREAD_M = 35.0

# --- Talep ---------------------------------------------------------------
PER_CAPITA_LPD = 150.0       # kalibrasyon yoksa kişi başı günlük tüketim (L)
PERSONS_PER_FLAT = 3.0
FLAT_GROSS_AREA_M2 = 100.0   # daire başına brüt kat alanı
NET_TO_GROSS = 0.85
MIN_FOOTPRINT_M2 = 30.0
FLOOR_HEIGHT_M = 3.0

# Konut sayılan bina etiketleri (İstanbul'da çoğu bina sadece building=yes)
RESIDENTIAL_TYPES = {
    "yes", "apartments", "residential", "house", "detached", "semidetached_house",
    "terrace", "dormitory", "bungalow",
}
# Konut dışı binalar için konut eşdeğeri talep katsayısı
NON_RESIDENTIAL_FACTOR = {
    "commercial": 0.5, "retail": 0.5, "office": 0.5, "hotel": 1.2, "hospital": 1.5,
    "school": 0.4, "university": 0.4, "kindergarten": 0.4, "public": 0.4, "civic": 0.4,
    "government": 0.4, "mosque": 0.1, "religious": 0.1, "church": 0.1,
    "industrial": 0.2, "warehouse": 0.1, "train_station": 0.2, "sports_hall": 0.3,
}
# Talebi olmayan yapılar
ZERO_DEMAND_TYPES = {
    "garage", "garages", "shed", "roof", "construction", "ruins", "carport", "parking",
    "hut", "greenhouse", "transformer_tower", "service", "kiosk", "container", "toilets", "shelter",
}
# building=yes etiketli bir yapının üstünde işlev etiketi varsa konut sayılmaz; talep katsayısı bu türden gelir.
# (Bayrampaşa'da Forum İstanbul ve CarrefourSA shop=mall, IKEA shop=furniture, karakol amenity=police; bunlar
# konut sayılınca binlerce "kişi" çıkıyordu.) Sözlükte olmayan amenity değerleri "public" sayılır.
FUNCTION_TAG_TYPES = {"shop": "retail", "office": "office", "tourism": "hotel", "healthcare": "hospital",
                      "leisure": "sports_hall"}
AMENITY_TYPES = {
    "school": "school", "college": "school", "university": "university", "kindergarten": "kindergarten",
    "hospital": "hospital", "clinic": "hospital", "doctors": "hospital", "place_of_worship": "religious",
    "parking": "parking", "bus_station": "parking", "shelter": "shelter", "fuel": "commercial",
    "cafe": "commercial", "restaurant": "commercial", "car_wash": "commercial", "marketplace": "commercial",
}
# İşlev etiketi olmayan building=yes yapılarda taban alanı bundan büyükse konut sayılmaz (AVM, fabrika, depo,
# otogar). Bayrampaşa'da building=yes yapıların %99'u 954 m²'den küçük; apartman blokları nadiren bu boyutta (tahmin).
LARGE_FOOTPRINT_M2 = 3000.0
NON_RESIDENTIAL_FACTOR["buyuk_yapi"] = 0.3   # türü bilinmeyen büyük yapı: konut dışı ortalama

# Konut tüketimi için 24 saatlik çarpanlar (00:00 … 23:00). Ortalaması 1'e normalize edilir.
DIURNAL_PATTERN = [
    0.55, 0.45, 0.40, 0.38, 0.40, 0.55, 0.95, 1.45, 1.55, 1.35, 1.15, 1.10,
    1.10, 1.05, 1.00, 1.00, 1.05, 1.15, 1.30, 1.45, 1.50, 1.40, 1.10, 0.80,
]

# --- Kaçak ----------------------------------------------------------------
# Fiziksel kaçağın şebekeye verilen suya oranı (İstanbul toplam kayıp-kaçak %18,6; bir kısmı ticari kayıp).
LEAK_SHARE = 0.12
# FAVAD N1 üssü: kaçak ∝ basınç^N1
LEAK_EXPONENT = 1.0

# --- Bina depoları ve hidroforlar (M1) ----------------------------------------
# Depo bulunma olasılığı: 5 ve üzeri katlı binaların çoğunda bodrum deposu + hidrofor var (anketle doğrulanacak)
TANK_SHARE_HIGH_RISE = 0.85     # kat >= 5
TANK_SHARE_LOW_RISE = 0.35      # kat 1-4
TANK_DAYS = 1.5                 # depo hacmi = günlük tüketim x bu katsayı
TANK_MIN_M3 = 1.0
TANK_MAX_M3 = 60.0
TANK_INLET_M3H = 3.6            # bina giriş bağlantısı kapasitesi (~1 L/s)
# Orkestratörün asla altına inmediği doluluk: kesinti ve deprem için yedek
RESERVE_FRACTION = 0.40
# Kitin takıldığı akıllı depoların payı (geri kalan şamandıralı vana gibi davranır)
PARTICIPATION = 1.0
# Hidrofor: bodrumdaki depodan en üst kata basma
BOOSTER_TOP_PRESSURE_M = 10.0
BOOSTER_EFFICIENCY = 0.50

# --- Enerji ---------------------------------------------------------------
# İdarenin DMA girişine suyu basma verimi; su deniz seviyesinden giriş enerji kotuna basılıyor kabul edilir
UTILITY_PUMP_EFFICIENCY = 0.70
# Üç zamanlı tarife (TL/kWh). Yaklaşık değerler: EPDK cetvelinden güncelleyin.
TARIFF_TL_PER_KWH = {"gece": 2.70, "gunduz": 4.30, "puant": 6.50}
# Saat -> dilim: gündüz 06-17, puant 17-22, gece 22-06
TARIFF_PERIOD = ["gece"] * 6 + ["gunduz"] * 11 + ["puant"] * 5 + ["gece"] * 2

# --- Orkestratör ------------------------------------------------------------
# Amaç = sum((Q/Qort)^2) + PRICE_WEIGHT * sum(fiyat_oranı * Q/Qort)
PRICE_WEIGHT = 0.30

# --- Basınç pilotu (M2) -----------------------------------------------------
# Kot farkı bundan büyük DMA'lar, basınç düşürücü vanalı alt bölgelere ayrılmak üzere önerilir
SUBZONE_ELEV_SPREAD_M = 12.0
# Pilotun önerdiği en fazla vana sayısı (en verimliden başlayarak)
PILOT_MAX_PRVS = 40
# Kaçan 1 m³ suyun değeri: arıtma ve iletimin değişken maliyeti (~0,6 kWh/m³ × ~4 TL/kWh + kimyasal).
# Tahmin; İSKİ'den doğrulanmalı. Kıtlık değeri dahil değil. Dağıtımdaki basma enerjisi ayrıca simülasyondan gelir.
WATER_VALUE_TL_M3 = 3.0
# Her aday vana DMA'nın alt modelinde tek tek simüle edilir; net kazancı (kaçak değeri − enerji maliyeti artışı)
# bu eşiğin altında kalan aday alınmaz (TL/gün).
PILOT_MIN_NET_TL_D = 0.0

# --- Kesinti günü (M2) ------------------------------------------------------
OUTAGE_START_HOUR = 10          # planlı çalışma 10:00'da başlar
OUTAGE_END_HOUR = 16            # 16:00'da su geri gelir
PREFILL_HOURS = 10              # orkestratör kesintiden önceki bu kadar saatte (gece dahil) depoları doldurur
# Basınca bağlı talep: 15 m'de talebin tamamı, 0 m'de hiç su
PDD_REQUIRED_PRESSURE_M = 15.0
PDD_MINIMUM_PRESSURE_M = 0.0

# --- Sızıntı avı (M2b) --------------------------------------------------------
# Yeni bir boru patlağının yeri binalardaki basınç sensörleriyle aranır. Ölçüm, gece en düşük debi
# saatinde yapılır; orkestratör ölçüm süresince akıllı depoların dolumunu durdurur (şebeke sessizleşir).
LEAK_EVENT_LPS = 2.0            # aranan sızıntının debisi (L/s); İstanbul'daki 100 mm hat arızaları bu düzeyde başlar (tahmin)
LEAK_DETECT_HOUR = 3            # ölçüm saati (gece en düşük debi)
LEAK_EVENTS = 6                 # rastgele sızıntı yeri sayısı (sonuçlar bunların ortalaması)
LEAK_DEMAND_NOISE = 0.10        # gece talebinin düğüm başına rastgele sapması (standart sapma, oran)
LEAK_SENSOR_NOISE_M = 0.05      # basınç sensörünün 15 dk ortalamasındaki rastgele hata (m). %0,25 sınıfı 10 bar sensörün
                                # sabit sapması kendi geçmişiyle karşılaştırınca düşer; kalan gürültü birkaç cm (tahmin)
LEAK_CONTROL_NOISE = 0.02       # kontrollü depo dolumunun bilinmeyen kısmı (seviye sensörü hatası, oran)
# Kontrollü yükleme: ölçüm sırasında akıllı depolar giriş kapasitesinin bu oranlarıyla doldurulur; en düşük basıncı
# hizmet sınırının üstünde tutan en büyüğü seçilir. Bilinen yük, sızıntının basınç izini büyütür.
LEAK_EXCITE_STEPS = (1.0, 0.7, 0.5, 0.35, 0.2, 0.1, 0.0)
LEAK_EXCITE_MINUTES = 15        # yüklemenin süresi; depolarda bu kadar dolum yeri olmalı
LEAK_NOISE_RUNS = 8             # gürültü düzeyini ölçmek için sızıntısız deneme sayısı
LEAK_SPARSE_SENSORS = 5         # geleneksel yaklaşım: DMA başına birkaç basınç kaydedici
LEAK_CONFIDENCE = 0.90          # arama alanı = olasılığın bu kadarını kapsayan en küçük düğüm kümesi

# --- Deprem günü (M2b) --------------------------------------------------------
# Senaryo: İBB 2019 deprem kayıp tahmini, 7,5 Mw gece depremi. Mahalle başına içme suyu borusu hasarı
# (data/ref/mahalle_deprem_2019.csv) ilçedeki borulara boru uzunluğuyla orantılı, sabit tohumla dağıtılır.
QUAKE_HOUR = 3                  # sarsıntı saati (gece senaryosu; 17 Ağustos 1999 depremi 03:02'de oldu)
# HAZUS (FEMA) su şebekesi modeli: yer sarsıntısının yol açtığı boru hasarında kırık payı %20, sızıntı payı %80.
# Kırık sayısı hasar sayısı × bu oran, yuvarlanarak; hangi noktaların kırık olduğu rastgele seçilir.
QUAKE_BREAK_SHARE = 0.20
# Kırık, borunun tam kesitinden atmosfere açılan bir uç; sızıntı, kesitin bu kadarı alanında bir delik (tahmin).
QUAKE_LEAK_AREA_FRACTION = 0.05
# Açıklıktan çıkış: Q = Cd · A · √(2gH). Modelde 1 m'lik, çek valfli kısa bir boru ve K = 1/Cd² yerel kaybıyla
# kurulur (su şebekeye geri giremez).
QUAKE_ORIFICE_CD = 0.60
# Şebeke suyu şüpheli: hasar noktası olan DMA'da (kırılma anındaki basınç dalgası kırık ve çatlaklardan kirli suyu
# boruya çekebilir; aynı sokaktaki atık su boruları da kırılır) ya da basıncı bu değerin altına inen DMA'da, o
# saatten itibaren. Su test edilene kadar içilemez kabul edilir. Eşik, ABD'de birçok eyaletin kaynatma uyarısı için
# kullandığı 20 psi (≈14 m). Orkestratör hasarlı DMA'yı sayaçtaki ani debi artışından tanır (en küçük sızıntı bile
# birkaç L/s); şebekenin geri kalanı için kaynatma uyarısı varsayılmaz (iyimser; kaynatma uyarısı bütün ilçeye
# verilirse şamandıralı depoların hepsi risk altına girer).
QUAKE_SUSPECT_PRESSURE_M = 14.0
# Depremden sonra binada kullanılan su: insanlar evden çıkar, elektrik çoğu yerde kesilir; tüketim temel ihtiyaca
# iner. Sphere el kitabının asgarisi (içme, yemek, temel hijyen) 15 L/kişi/gün. Bütün binalar ve iki senaryo için
# aynıdır (tahmin). Konut dışı binalar (dükkân, okul) depremden sonra su çekmez.
QUAKE_USE_LPCD = 15.0
# Temiz su stoku kişi-gün olarak bu içme suyu ihtiyacıyla ölçülür (Sphere: hayatta kalma için 2,5–3 L/kişi/gün).
QUAKE_DRINK_LPCD = 3.0
# Akıllı kit: ivmeölçer sarsıntıyı algılayınca depo girişini kapatır (bütün akıllı depolar). Orkestratör bu kadar
# saat sonra şebeke suyu şüpheli olmayan DMA'larda girişleri açar ve depoları tamamlar (dolum, kesinti günündeki
# gibi basıncı 15 m'nin altına indirmeyecek kadar). Şüpheli DMA'da depo gün boyu mühürlü kalır; mühürlü bir depo
# boşalmak üzereyse kit girişi açar (bina susuz kalmasın), o depo şüpheli su aldığı için kirlenme riskine girer.
QUAKE_REOPEN_AFTER_H = 1
# Duyarlılık ayarları (scripts/deprem_duyarlilik.py). Şüpheli alanın kapsamı: "dma" (yukarıdaki kural) ya da "ilce"
# (kaynatma uyarısı bütün ilçeye verilir). Arz tarafı modelde yok; elektrik ya da terfi kesintisinin etkisini görmek
# için sarsıntıdan sonra bütün DMA giriş kotları bu kadar düşürülebilir (m).
QUAKE_SUSPECT_SCOPE = "dma"
QUAKE_HEAD_DROP_M = 0.0

# --- Güneşle dolum (21 Kas) ------------------------------------------------------
# Orkestratör bugünkü üç zamanlı tarife yerine elektrik piyasasının saatlik fiyatına bakar. Profil gerçek bir gün:
# EPİAŞ Gün Öncesi Piyasası, 26.10.2025, PTF (TL/MWh). Öğlen güneş üretimi bolken fiyat sıfıra yaklaşıyor.
SOLAR_PRICE_DATE = "26.10.2025"
SOLAR_PRICE_TL_MWH = [
    3350.00, 3250.01, 3200.01, 3334.43, 3349.70, 3155.00, 3391.32, 2936.00, 1606.97, 850.00, 128.28, 10.01,
    1.00, 1.01, 80.00, 395.10, 3233.07, 3400.00, 3400.00, 3400.00, 3400.00, 3400.00, 2807.77, 1606.98,
]
# Fiyatın düzleştirmeye göre ağırlığı (orkestratörün PRICE_WEIGHT'i yerine). 1,0 dolumu güneş saatlerine toplar ama
# tepe debisini düşürmez; 0,3 tepeyi de düşürür, maliyet daha az iner (scripts/gunes_dolum.py).
SOLAR_PRICE_WEIGHT = 1.0
SOLAR_HOURS = (9, 16)           # güneş saatleri sayılan aralık, raporlama için

# --- Basınçtan enerji (21 Kas) -------------------------------------------------
# Depo girişinde şebeke basıncı vanada yok olur; girişe konan mikro türbin bunun bir kısmını elektriğe çevirir.
# Küçük debide (bina başına birkaç L/dk) türbin verimi düşüktür (tahmin; üretici verisiyle doğrulanmalı).
TURBINE_EFFICIENCY = 0.40
TURBINE_RESIDUAL_M = 3.0        # türbinden sonra depoya dolum için bırakılan basınç (m)
# Kitin ortalama elektrik ihtiyacı: denetleyici uykuda, LTE-M 15 dakikada bir, sensörler ve vana (tahmin)
KIT_POWER_W = 3.0

# --- Yağmur deposu ve sel tamponu (21 Kas) ---------------------------------------
# İstanbul aylık yağış ortalamaları, mm (MGM resmi iklim istatistikleri, 1950–2025; toplam ~659 mm)
RAIN_MONTHLY_MM = [88.8, 70.7, 62.3, 47.8, 32.9, 27.6, 22.1, 23.9, 39.7, 66.3, 78.1, 99.2]
RAIN_RUNOFF_COEF = 0.8          # çatıdan depoya ulaşan pay (buharlaşma, ilk yıkama, taşma; tahmin)
# Depo hacmi = yıllık toplanabilir suyun bu oranı (Planlı Alanlar İmar Yönetmeliği, TS EN 16941-1 yöntemi: en az %6).
# Senaryo: her konut binasında yağmur deposu var (bugün yalnız 2.000 m² üstü parsellerdeki yeni binalarda zorunlu).
RAIN_TANK_SHARE = 0.06
# Sağanaktan önce klasik deponun doluluğu: aynı hafta yağışlıysa depo büyük ölçüde doludur (tahmin)
RAIN_PASSIVE_START = 0.9
# Denenen sağanaklar (mm/gün). 203,9 mm: 13–14 Ekim 2026'da Bayrampaşa'nın komşusu Eyüpsultan'da (İBB AKOM)
RAIN_EVENTS_MM = (50.0, 100.0, 203.9)
# Yağmur suyunun kullanılabildiği içme dışı tüketim payı (tuvalet, temizlik, bahçe; tahmin)
RAIN_NONPOTABLE_SHARE = 0.25

# --- Simülasyon ------------------------------------------------------------
HOURS = 24
