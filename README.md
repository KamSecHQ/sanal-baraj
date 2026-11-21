# Sanal Baraj · Dijital İkiz (M2b)

**Canlı dijital ikiz:** https://kamsechq.github.io/sanal-baraj/ · Takım **AQUAİST** · Water AI Hackathon 2026 (Wilo Türkiye)

> Tarayıcıda açılır, kurulum gerekmez. Üstteki sekmeler: normal gün, kesinti günü, deprem günü, sızıntı avı,
> İstanbul öncelik haritası. **Sunum** düğmesi (ya da `S`) 15 adımlık anlatımı başlatır.

İlçe adını ver; OpenStreetMap'ten bir su şebekesi üretsin, bina depolarını ve hidroforları eklesin, normal bir
günü üç senaryoyla, planlı kesinti gününü ve deprem gününü ikişer senaryoyla simüle etsin, gece bir sızıntının
yerini binalardaki basınç sensörleriyle arasın ve sonucu haritada saat saat göstersin. Water AI Hackathon 2026 alet çantası.

## Kurulum

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python scripts/fetch_ibb_ref.py   # İBB referans tablolarını yeniler (data/ref içinde hazır geliyor)
```

## Kullanım

```bash
.venv/bin/python -m twin.build Bayrampaşa                    # ana ilçe, ~25 sn (ilk sefer OSM indirmesiyle ~5 dk)
.venv/bin/python -m twin.build Avcılar --mahalle Gümüşpala   # tek mahalle, birkaç saniye
.venv/bin/python scripts/fetch_ilce_sinirlari.py             # İstanbul ilçe sınırları (data/ref içinde hazır)
python3 scripts/serve.py                                      # sonra: http://localhost:8765/web/
python3 scripts/serve.py --lan                                # aynı ağdaki tablet ya da ikinci bilgisayar için
```

## Harita arayüzü

Derleme adımı yok; bütün bağımlılıklar `web/vendor/` içinde, internetsiz açılır (altlık harita yoksa düz zemin).

| Görünüm (kısayol) | Ne gösterir |
|---|---|
| Normal gün (`N`) | Dört senaryo (kapalı, akıllı depo, + basınç pilotu, güneşle dolum); bina renkleri depo doluluğu, borular debi, düğümler basınç. Solda sanal baraj göstergesi, saatlik göstergeler, gün akışı, günün hesabı |
| Kesinti günü (`K`) | Planlı kesinti ve su dönüşü; şamandıra ile orkestratör |
| Deprem günü (`D`) | İBB 2019 senaryosunun boru hasarı; şamandıranın şüpheli suyu çekmesi ile kitin depoyu mühürlemesi, mahalle başına temiz su haritası |
| Sızıntı avı (`L`) | Gece sızıntısının olası yerleri, %90 güven alanı, gerçek yer; sayaç, 5 kaydedici ve akıllı kit karşılaştırması |
| Nereden başlamalı (`I`) | İstanbul'un 39 ilçesi: öncelik, su sorunu, uygunluk, susuzluk şikâyeti; ilçe ayrıntısı |

- **Sunum modu (`S`):** jüriye 15 adımlık anlatım; her adım haritayı, senaryoyu ve saati kurar, rakamları o
  ilçenin simülasyonundan alır. Sunum kumandası (PageDown/PageUp) ve ok tuşlarıyla ilerler. Metinler `web/js/story.js`.
- **Karşılaştırma (`B` basılı):** aynı an yapay zekâ kapalıyken nasıldı.
- Haritada bir öğeye tıklayınca sağda 24 saatlik eğrisi açılır (bina deposu, düğüm basıncı, boru debisi, DMA girişi, vana;
  deprem gününde boru hasarı ve mahalle temiz suyu).
- `Boşluk` oynat, `←` `→` saat, `1` `2` `3` senaryo, `T` açık tema (projeksiyon), `F` sığdır, `?` yardım.
- URL durumu taşır (`?d=bayrampasa&m=outage&s=on&h=16`): sunum için yer imi olarak saklanabilir.

İlk çalıştırmada OSM verisi ve yükseklik paftası `data/cache` altına kaydedilir; sonrakiler internetsiz çalışır.

| Seçenek | Varsayılan | Anlamı |
|---|---|---|
| `--network-state` | `tasarim` | `tasarim`: yeni ve cömert boyutlu şebeke. `mevcut`: pürüzlenmiş borular, daha çok yük kaybı. |
| `--participation` | 1,0 | Depoların kaçta kaçına akıllı kit takılı. |
| `--subzone-spread` | 12 | Basınç pilotunun önerdiği alt bölgelerde en büyük kot farkı (m). |
| `--outage-dma` | en kalabalık | Kesinti günü senaryosunun DMA'sı, ör. `DMA-12`. |
| `--leak-share` | 0,12 | Fiziksel kaçağın şebekeye verilen suya oranı (kapalı senaryoda). |
| `--max-spread` | 35 | Bir DMA içindeki en büyük kot farkı (m). |
| `--no-quake` | | Deprem gününü çalıştırma (mahalle sınırları da indirilmez). |
| `--per-capita`, `--nodes-per-dma`, `--no-dem`, `--seed` | | |

## Normal gün: üç senaryo

| | Yapay zekâ kapalı | Akıllı depo | Akıllı depo + basınç pilotu |
|---|---|---|---|
| Depo girişi | Şamandıralı vana | Orkestratörün 24 saatlik dolum planı | Aynı plan |
| Basınç | DMA girişi, kritik düğüm 22 m | Aynı kural, yeni talep profiline göre | En verimli 40 alt bölge kendi basınç düşürücü vanasıyla, her biri kritik düğümde 22 m |

**Orkestratör** (`twin/orchestrator.py`) her DMA için karesel bir program çözer: girişi düzleştirir, dolumu
puant saatlerden geceye kaydırır, depoları %40 yedeğin altına indirmez.

**Basınç pilotu** (`twin/pressure.py`) kaçağı düşürmek için basınç düşürücü vana (PRV) yerlerini önerir.
Dik DMA'ları kot farkı küçük alt bölgelere böler, her adayın günlük kaçak kazancını düğüm basınçlarından tahmin
eder, sonra her adayı DMA'nın tek başına modelinde gün boyu simüle eder ve net kazancıyla (kaçak azalması ×
suyun değeri − basma maliyeti artışı) seçer; enerjiyi kazancından çok artıranlar elenir. Bu, her binadaki kit sensörünün
sağladığı yoğun basınç haritası olmadan yapılamaz. Enerji hesabında su ana DMA'nın kotuna basılmış sayılır;
PRV fazla basıncı yok eder, pompa enerjisini geri kazandırmaz.

### Avcılar sonuçları (tasarim, katılım %100)

| | Kapalı | Akıllı depo | + Basınç pilotu |
|---|---|---|---|
| Tepe debisi (m³/sa) | 4.153 | 2.972 (−%28,4) | 2.945 (−%29,1) |
| Basma maliyeti (TL/gün) | 122.332 | 111.180 (−%9,1) | 110.197 (−%9,9) |
| Kaçak (m³/gün) | 8.126 | 8.088 (−%0,5) | 7.459 (**−%8,2**) |
| Ortalama basınç (m) | 35,9 | 35,8 | 32,9 (−%8,5) |
| Depoda su yaşı (sa) | 35,2 | 24,8 | 24,8 |
| En düşük depo yedeği (sa) | 35,2 | 21,8 | 21,8 |

Bulgular:
- Depo orkestrasyonu tepe yükünü ve maliyeti düşürür, kaçağı neredeyse düşürmez (fazla basınç kot farkından geliyor).
- Saatlik giriş basıncı ayarı da denendi; bu şebekede kazancı %0,1, bu yüzden pilota alınmadı.
- Kaçağı düşüren kaldıraç alt basınç bölgeleri. 188 adaydan 125 tanesi simülasyonda net kazançlı; en iyi 40 tanesi kaçağı
  %8,2 düşürüyor. Bayrampaşa'da 84 adaydan seçilen 40 vana kaçağı %12,5, enerjiyi %1,6 düşürüyor (tahminle
  seçildiğinde enerji %8,9 artıyordu).

## Kesinti günü

Seçilen DMA'da 10:00–16:00 planlı çalışma (`twin/outage.py`). Şebeke saat saat, basınca bağlı talep (PDD) ile
çözülür: basıncı 15 m'nin altına düşen düğüm istediği suyun bir kısmını alabilir.

- **Şamandıralı vana:** su gelince her depo açığını en hızlı şekilde doldurmaya çalışır.
- **Orkestratör:** depoları gece doldurur; su gelince her saat dolumu önce simüle eder ve basıncı 15 m'nin
  altına indirmeyecek kadar su bırakır. Deposuz binalar her zaman önceliklidir.

Avcılar, DMA-23 (36.648 kişi; deposuz binalarda 15.099 kişi):

| | Şamandıra | Orkestratör |
|---|---|---|
| Su dönünce tepe debisi (m³/sa, normal tepe 267) | 740 | 529 |
| Dönüşte en düşük basınç (m) | 9,4 | 16,7 |
| Dönüşte yetersiz basınç (düğüm-saat) | 62 | 0 |
| Dönüş sonrası susuz (kişi-saat) | 305 | 0 |
| Kesinti boyunca susuz (kişi-saat) | 90.594 | 90.594 |

Kesinti boyunca susuz kalanlar yalnızca deposuz binalar; depolu binalarda kimse susuz kalmıyor. Bu, depo
yaygınlaştırmanın kendisinin de güçlü bir argüman olduğunu gösteriyor.

## Sızıntı avı

`twin/leak.py`, kesinti günüyle aynı DMA'da gece saat 03:00 başında 2 L/s debili yeni bir sızıntıyı arar. DMA'nın tek başına
modelinde her aday düğüm için basınç imzası hesaplanır; gürültülü gözleme (gece talebi ±%10, sensör ±0,05 m) en iyi
uyan adaylar, bilinmeyen sızıntı büyüklüğüyle en büyük olabilirlik yöntemiyle olasılıklandırılır. Arama alanı,
olasılığın %90 kadarını kapsayan düğümlere bağlı boru uzunluğudur. Ölçümü orkestratör yönetir: dolumu durdurur (sessiz
şebeke), sonra depoları bilinen debiyle doldurur (kontrollü yükleme, sahadaki adım testinin kitle yapılan hali).

| Arama alanı (6 olay ortalaması) | Bayrampaşa DMA-03 | Avcılar DMA-23 |
|---|---|---|
| Yalnız DMA sayacı | 27,1 km | 28,3 km |
| 5 kaydedici | 22,2 km | 10,0 km |
| Akıllı kit, yüklemesiz | 19,1 km | 10,0 km |
| Akıllı kit, kontrollü yükleme | 6,4 km (6/6 isabet) | 2,8 km (5/6 isabet) |

## Deprem günü

`twin/quake.py`, İBB 2019 deprem senaryosunun (7,5 Mw, gece) mahalle başına içme suyu borusu hasarını OSM mahalle
sınırlarıyla ilçenin borularına dağıtır (sınır yoksa ilçe toplamı bütün borulara). HAZUS oranıyla beşte biri kırık
(tam kesit), gerisi sızıntı; her hasar çek valfli kısa bir çıkış borusuyla atmosfere açılır. Sarsıntı saat 03:00
başında; şebeke saat saat basınca bağlı taleple çözülür. Hasarlı ya da basıncı 14 m altına
inen DMA'nın şebeke suyu şüpheli sayılır. Şamandıralı depo bu suyu çeker ve kirlenme riskine girer; kitin
ivmeölçeri depo girişini mühürler, orkestratör sağlam DMA'larda girişleri bir saat sonra açar.

| Gün sonu, şamandıra / kit | Bayrampaşa | Avcılar |
|---|---|---|
| İBB hasarı → modelde | 8 → 2 kırık, 6 sızıntı | 22 → 4 kırık, 18 sızıntı |
| Şebeke suyu şüpheli DMA | 8 / 23 | 16 / 75 |
| Depolardaki temiz su (m³) | 15.212 / 28.870 | 39.920 / 51.371 |
| İlçe nüfusuna içme suyu (gün, 3 L/kişi) | 16,7 / 31,6 | 23,8 / 30,6 |
| Kirlenme riskindeki depo (bina) | 6.258 / 0 | 3.965 / 0 |

Duyarlılık: `.venv/bin/python scripts/deprem_duyarlilik.py Bayrampaşa` hasar yerleşimini (5 tohum), kırık oranını,
kaynatma uyarısının kapsamını ve DMA giriş kotunu değiştirir (`data/<bölge>/deprem_duyarlilik.csv`). Kitin temiz su
kazancı her varyantta korunur; susuz kişi iki modda aynıdır ve hasarın yerine çok bağlıdır.

## Güneşle dolum

Normal günün dördüncü senaryosu (`4`): orkestratör üç zamanlı tarife yerine elektrik piyasasının saatlik gün öncesi
fiyatına bakar (EPİAŞ GÖP; fiyat bir gün önceden yayımlanır). Öğlen güneş elektriği bolken fiyat sıfıra yaklaşıyor,
depolar o saatlerde dolar. Arayüzdeki gün 26.10.2025; `scripts/gunes_dolum.py` beş gerçek günü dener.

| Gün (Bayrampaşa) | Öğle fiyatı, TL/MWh | Piyasa maliyeti, güneş odaklı | Bugünkü tarifeyle |
|---|---|---|---|
| 11.05.2025, bahar | 112 | −%25,9 | +%8,7 |
| 26.10.2025, sonbahar | 44 | −%15,8 | +%3,9 |
| 14.12.2025, kış | 1.597 | −%7,0 | −%4,4 |
| 25.08.2026, yaz | 2.375 | −%2,3 | −%0,1 |
| 17.07.2025, sıcak yaz | 3.103 | −%0,1 | 0 |

Kapalıya göre; beş günün ortalaması −%8. Bedeli: fiyat ağırlığı 1,0 iken tepe debisi düşmüyor (0,3 ile tepe de
düşer, maliyet daha az iner).

## Basınçtan enerji

`twin/energy.py`: su depoya şebeke basıncıyla gelir (Bayrampaşa'da ortalama ~35 m), vana bu basıncı yok eder, sonra
hidrofor suyu yeniden basar. Bayrampaşa'da depo girişlerinde günde ~2.500 kWh hidrolik enerji boşa gidiyor;
hidroforlar ~4.250 kWh elektrik harcıyor. Girişe mikro türbin (verim %40, tahmin) konursa depolu binaların ~%31
kadarında kit (ortalama 3 W, tahmin) kendi enerjisini üretir. Şebeke basıncının yettiği alt katları doğrudan
beslemek hidrofor enerjisini çok azaltır ama o talep sanal barajdan çıkıp şebekenin tepe saatine döner; önerilmiyor.
Bina incelemesinde her binanın enerji bütçesi görünür. Basınç pilotunun vanalarındaki enerji: `scripts/vana_turbin.py`.

## Modüller

| Modül | Ne yapıyor |
|---|---|
| `twin/osm.py` | İlçe sınırı, yol ağı, bina ayak izleri. Otoyollar hariç her yol bir boru adayı. |
| `twin/dem.py` | Copernicus GLO-30 kotları; 3x3 minimum ve sokak eğimine göre sapma temizliği. |
| `twin/demand.py` | Bina alanı × kat → daire → kişi; kat etiketi yoksa İBB 2017 dağılımından örnek. |
| `twin/network.py` | DMA bölme, boru boyutlandırma, giriş basıncı ayarı, basınca bağlı kaçak. |
| `twin/tanks.py` | Depo ataması (5+ katta %85, 1–4 katta %35), hacim (1,5 günlük tüketim), hidrofor gücü. |
| `twin/orchestrator.py` | DMA başına dolum planı (cvxpy + Clarabel). |
| `twin/pressure.py` | Basınç pilotu: aday alt bölgeler, kazanç tahmini, seçim, uygulama. |
| `twin/outage.py` | Kesinti günü, saat saat PDD simülasyonu. |
| `twin/leak.py` | Sızıntı avı: aday imzaları, gürültü, en büyük olabilirlik, üç sensör düzeni. |
| `twin/energy.py` | Basınçtan enerji: depo girişinde boşa giden basınç, mikro türbin, doğrudan besleme. |
| `twin/quake.py` | Deprem günü: İBB mahalle hasarını borulara dağıtma, kırık ve sızıntı açıklıkları, saat saat PDD, kit mühürü, temiz su. |
| `twin/scenario.py` | Senaryoyu modele uygular, simüle eder, göstergeleri hesaplar. |
| `twin/pipeline.py` | Bütün senaryoları sırayla kurar ve çalıştırır. |
| `twin/export.py` | GeoJSON, `summary.json`, üç EPANET modeli. |
| `web/` | MapLibre kontrol odası. `js/main.js` bağlar; `map` katmanlar, `panel` sol panel (normal, kesinti, deprem), `timeline` zaman şeridi, `inspector` seçim, `legend`, `story` sunum, `istanbul`, `leak`, `data` yükleme ve gün akışı, `charts` SVG grafikler. |

Varsayılan parametreler `twin/config.py` içinde. Her biri bir varsayım; su mühendisi gözden geçirmeli.
Tarife değerleri (gece 2,70, gündüz 4,30, puant 6,50 TL/kWh) yaklaşıktır; EPDK cetvelinden güncelleyin.

## Çıktılar (`data/<bölge>/`)

- `nodes.geojson`: kot, DMA; `p*` (kapalı), `pa*` (akıllı depo), `pb*` (pilot) saatlik basınç; kesinti DMA'sında `o*` ve `oa*`;
  deprem gününde bütün düğümlerde `e*` (şamandıra) ve `ea*` (kit)
- `pipes.geojson`: çap, uzunluk; `q*`, `qa*`, `qb*` saatlik debi; `b` DMA sınırı, `bp` pilotun kapattığı sınır
- `buildings.geojson`: kat, kişi, tüketim, depo `tv`, kit `sm`, hidrofor `hb`; `l*` akıllı depo doluluğu; kesinti DMA'sında `ol*` ve `oal*`;
  deprem gününde alan sırası `ar`, deponun kirlenme riskine girdiği saat `ek` (şamandıra) ve `eka` (kit)
- `prvs.geojson`: önerilen vanalar, sıra, tahmini kazanç
- `leak.json`: sızıntı avı (DMA düğümleri, sensör düzenleri, her olay için aday olasılıkları ve arama alanı)
- `quake.json`: deprem günü (hasar noktaları ve saatlik debileri, mahalle ya da DMA alanları ve saatlik temiz suyu, DMA durumları)
- `dmas.geojson`, `inlets.geojson`, `summary.json`
- `model.inp`, `model_yapay_zeka.inp`, `model_basinc_pilotu.inp`: EPANET 2.2 modelleri

## Test

```bash
.venv/bin/python -m pytest -q tests
```

Testler internetsizdir: sentetik bir ızgarada orkestratörün tepe debisini düşürdüğünü ve depo sınırlarına
uyduğunu, pilotun hizmet basıncını bozmadan kaçağı düşürdüğünü ve her alt bölgenin ana bölgeye değdiğini,
kesinti dönüşünde orkestratörün basıncı koruduğunu, yoğun sensörün sızıntı arama alanını daralttığını, depremde
kitin depo suyunu temiz tuttuğunu ve dışa aktarımın tutarlı olduğunu doğrular.

## Sınırlar

- Sentetik şebeke, gerçek İSKİ şebekesi değil. DMA ve alt bölge girişleri sabit kotlu depo olarak modellenir.
- Basma enerjisi, suyun deniz seviyesinden DMA giriş kotuna basıldığı varsayımıyla hesaplanır (verim 0,70).
- Hidrofor enerjisi bütün senaryolarda aynıdır, karşılaştırmaya girmez.
- Talep tahmini mükemmel kabul edilir.
- Vana kurulum maliyeti henüz yok; suyun değeri (3 TL/m³) tahmindir, İSKİ'den doğrulanmalı.
- Sızıntı avının gürültü varsayımları tahmindir; güven alanı biraz iyimser (Avcılar'da 6 olaydan 5 tanesinde isabet).
- Nüfus tahmini şişkin (Avcılar'da ~559 bin; Bayrampaşa'da 304 bin, TÜİK 2024 nüfusu 268 bin); toplam talep İBB
  tüketimine kalibre olduğu için hidrolik doğru kalır. İşlev etiketli (`shop`, `amenity`, `office`...) ya da
  3.000 m² üstü etiketsiz `building=yes` yapılar konut sayılmaz (`demand.building_type`).
- Deprem gününde DMA girişleri sınırsız kaynak: terfi merkezi, iletim hattı ve elektrik kesintisi yok, bu yüzden basınç
  yalnız hasarın çevresinde düşer. Şebeke suyunun şüpheli sayılması (hasarlı ya da basıncı 14 m altına inen DMA) ve
  deprem sonrası tüketim (15 L/kişi/gün) varsayımdır.

## Sırada

Takımla sunum provası, Bayrampaşa için mahalle düzeyinde yüksek çözünürlük, doğrulama ilçeleri, deprem modu,
talep tahmini, Konuşan Su ve M3. Ayrıntılı plan ve öncelik sırası: `docs/RAPOR.md` bölüm 10.
