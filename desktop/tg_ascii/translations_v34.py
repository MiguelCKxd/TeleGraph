"""Media quality controls introduced in 3.4; no I/O at import time."""
KEYS = (
    'Original media in the viewer',
    'Show photos at the highest quality available from Telegram, without recompression. Previews stay small. Uses more data and memory.',
    'Photos and videos', 'SD · Standard', 'HD · High quality', 'Original as file',
)
ROWS = {
    'es': 'Originales en el visor|Mostrar las fotos con la máxima calidad disponible en Telegram, sin recomprimir. Las vistas previas siguen reducidas. Usa más datos y memoria.|Fotos y vídeos|SD · Estándar|HD · Alta calidad|Original como archivo',
    'ru': 'Оригиналы в просмотрщике|Показывать фото в максимальном качестве Telegram без повторного сжатия. Превью остаются небольшими. Использует больше трафика и памяти.|Фото и видео|SD · Стандартное|HD · Высокое качество|Оригинал как файл',
    'pl': 'Oryginały w przeglądarce|Pokazuj zdjęcia w najwyższej jakości dostępnej w Telegramie, bez ponownej kompresji. Podglądy pozostają małe. Zużywa więcej danych i pamięci.|Zdjęcia i filmy|SD · Standardowa|HD · Wysoka jakość|Oryginał jako plik',
    'ca': 'Originals al visor|Mostra les fotos amb la màxima qualitat disponible a Telegram, sense recomprimir. Les previsualitzacions continuen reduïdes. Consumeix més dades i memòria.|Fotos i vídeos|SD · Estàndard|HD · Alta qualitat|Original com a fitxer',
    'uk': 'Оригінали в переглядачі|Показувати фото в найвищій доступній якості Telegram без повторного стиснення. Мініатюри залишаються малими. Використовує більше даних і пам’яті.|Фото й відео|SD · Стандартна|HD · Висока якість|Оригінал як файл',
    'zh-Hans': '查看器中的原始媒体|以 Telegram 提供的最高画质显示照片，不重新压缩。预览图仍保持较小尺寸。会使用更多流量和内存。|照片和视频|SD · 标准|HD · 高画质|以文件发送原图',
    'ko': '뷰어에서 원본 보기|재압축 없이 Telegram에서 제공하는 최고 화질로 사진을 표시합니다. 미리보기는 작게 유지됩니다. 데이터와 메모리를 더 사용합니다.|사진 및 동영상|SD · 표준|HD · 고화질|원본 파일로 보내기',
    'ja': 'ビューアでオリジナルを表示|再圧縮せずにTelegramで利用できる最高画質の写真を表示します。プレビューは小さいままです。データとメモリをより多く使用します。|写真と動画|SD · 標準|HD · 高画質|オリジナルをファイルとして送信',
    'it': 'Originali nel visualizzatore|Mostra le foto alla massima qualità disponibile su Telegram, senza ricompressione. Le anteprime restano piccole. Usa più dati e memoria.|Foto e video|SD · Standard|HD · Alta qualità|Originale come file',
    'pt': 'Originais no visualizador|Mostrar fotos na qualidade máxima disponível no Telegram, sem recompressão. As prévias continuam pequenas. Usa mais dados e memória.|Fotos e vídeos|SD · Padrão|HD · Alta qualidade|Original como arquivo',
    'el': 'Πρωτότυπα στην προβολή|Εμφάνιση φωτογραφιών στη μέγιστη διαθέσιμη ποιότητα του Telegram, χωρίς επανασυμπίεση. Οι προεπισκοπήσεις παραμένουν μικρές. Χρησιμοποιεί περισσότερα δεδομένα και μνήμη.|Φωτογραφίες και βίντεο|SD · Τυπική|HD · Υψηλή ποιότητα|Πρωτότυπο ως αρχείο',
    'eu': 'Jatorrizkoak ikustailean|Erakutsi argazkiak Telegramen eskuragarri dagoen kalitate handienean, berriro konprimitu gabe. Aurrebistak txikiak dira oraindik. Datu eta memoria gehiago erabiltzen ditu.|Argazkiak eta bideoak|SD · Estandarra|HD · Kalitate handia|Jatorrizkoa fitxategi gisa',
    'gl': 'Orixinais no visor|Mostrar as fotos coa máxima calidade dispoñible en Telegram, sen recomprimir. As vistas previas seguen reducidas. Usa máis datos e memoria.|Fotos e vídeos|SD · Estándar|HD · Alta calidade|Orixinal como ficheiro',
    'oc-aran': 'Originaus en visor|Mostrar es fotos damb era maxima qualitat disponibla en Telegram, sense recomprimir. Es previsualizacions demoren petites. Utilize mès donades e memòria.|Fotos e vidèos|SD · Estandard|HD · Nauta qualitat|Originau coma fichèr',
    'an': 'Orichinals en o visor|Amostrar as fotos con a maxima calidat disponible en Telegram, sin recomprimir. As vistas previas siguen reducidas. Usa más datos y memoria.|Fotos y vídeos|SD · Estándar|HD · Alta calidat|Orichinal como fichero',
    'de': 'Originale im Betrachter|Fotos in der höchsten auf Telegram verfügbaren Qualität ohne erneute Komprimierung anzeigen. Vorschauen bleiben klein. Benötigt mehr Daten und Speicher.|Fotos und Videos|SD · Standard|HD · Hohe Qualität|Original als Datei',
    'fr': 'Originaux dans la visionneuse|Afficher les photos dans la meilleure qualité disponible sur Telegram, sans recompression. Les aperçus restent petits. Utilise davantage de données et de mémoire.|Photos et vidéos|SD · Standard|HD · Haute qualité|Original comme fichier',
    'ar': 'الوسائط الأصلية في العارض|عرض الصور بأعلى جودة متاحة في تيليجرام دون إعادة ضغط. تظل المعاينات صغيرة. يستخدم مزيدًا من البيانات والذاكرة.|الصور والفيديوهات|SD · قياسية|HD · جودة عالية|الأصل كملف',
    'nl': 'Originelen in de viewer|Toon foto’s in de hoogste kwaliteit die Telegram biedt, zonder opnieuw te comprimeren. Voorbeelden blijven klein. Gebruikt meer data en geheugen.|Foto’s en video’s|SD · Standaard|HD · Hoge kwaliteit|Origineel als bestand',
    'fi': 'Alkuperäiset katseluohjelmassa|Näytä kuvat Telegramin parhaalla saatavilla olevalla laadulla ilman uudelleenpakkausta. Esikatselut pysyvät pieninä. Käyttää enemmän dataa ja muistia.|Kuvat ja videot|SD · Normaali|HD · Korkea laatu|Alkuperäinen tiedostona',
    'be': 'Арыгіналы ў праглядальніку|Паказваць фота ў найвышэйшай даступнай якасці Telegram без паўторнага сціскання. Мініяцюры застаюцца малымі. Выкарыстоўвае больш даных і памяці.|Фота і відэа|SD · Стандартная|HD · Высокая якасць|Арыгінал як файл',
    'ro': 'Originale în vizualizator|Afișează fotografiile la cea mai bună calitate disponibilă pe Telegram, fără recomprimare. Previzualizările rămân mici. Folosește mai multe date și memorie.|Fotografii și videoclipuri|SD · Standard|HD · Calitate înaltă|Original ca fișier',
    'sv': 'Original i visaren|Visa foton med högsta tillgängliga kvalitet på Telegram utan ny komprimering. Förhandsvisningar förblir små. Använder mer data och minne.|Foton och videor|SD · Standard|HD · Hög kvalitet|Original som fil',
    'nb': 'Originaler i visningen|Vis bilder med høyeste tilgjengelige kvalitet på Telegram, uten ny komprimering. Forhåndsvisninger forblir små. Bruker mer data og minne.|Bilder og videoer|SD · Standard|HD · Høy kvalitet|Original som fil',
    'hi': 'व्यूअर में मूल मीडिया|फ़ोटो को दोबारा संपीड़ित किए बिना Telegram पर उपलब्ध उच्चतम गुणवत्ता में दिखाएँ। पूर्वावलोकन छोटे रहते हैं। अधिक डेटा और मेमोरी लगती है।|फ़ोटो और वीडियो|SD · मानक|HD · उच्च गुणवत्ता|मूल फ़ाइल के रूप में',
    'th': 'สื่อต้นฉบับในตัวแสดง|แสดงรูปภาพด้วยคุณภาพสูงสุดที่มีใน Telegram โดยไม่บีบอัดซ้ำ ภาพตัวอย่างยังคงมีขนาดเล็ก ใช้ข้อมูลและหน่วยความจำมากขึ้น|รูปภาพและวิดีโอ|SD · มาตรฐาน|HD · คุณภาพสูง|ต้นฉบับเป็นไฟล์',
    'bn': 'ভিউয়ারে মূল মিডিয়া|পুনরায় সংকোচন ছাড়াই Telegram-এ উপলব্ধ সর্বোচ্চ মানে ছবি দেখান। প্রিভিউ ছোটই থাকে। বেশি ডেটা ও মেমরি ব্যবহার করে।|ছবি ও ভিডিও|SD · সাধারণ|HD · উচ্চ মান|মূলটি ফাইল হিসেবে',
    'fil': 'Mga orihinal sa viewer|Ipakita ang mga larawan sa pinakamataas na kalidad na available sa Telegram, nang walang muling compression. Maliit pa rin ang mga preview. Gumagamit ng mas maraming data at memory.|Mga larawan at video|SD · Karaniwan|HD · Mataas na kalidad|Orihinal bilang file',
    'ur': 'ویوئر میں اصل میڈیا|تصاویر کو دوبارہ کمپریس کیے بغیر Telegram پر دستیاب بہترین معیار میں دکھائیں۔ پیش منظر چھوٹے رہتے ہیں۔ زیادہ ڈیٹا اور میموری استعمال ہوتی ہے۔|تصاویر اور ویڈیوز|SD · معیاری|HD · اعلیٰ معیار|اصل بطور فائل',
    'vi': 'Bản gốc trong trình xem|Hiển thị ảnh ở chất lượng cao nhất có trên Telegram, không nén lại. Bản xem trước vẫn nhỏ. Dùng nhiều dữ liệu và bộ nhớ hơn.|Ảnh và video|SD · Tiêu chuẩn|HD · Chất lượng cao|Bản gốc dưới dạng tệp',
    'he': 'מקוריים במציג|הצגת תמונות באיכות הגבוהה ביותר הזמינה בטלגרם, ללא דחיסה מחדש. התצוגות המקדימות נשארות קטנות. משתמש ביותר נתונים וזיכרון.|תמונות וסרטונים|SD · רגילה|HD · איכות גבוהה|מקור כקובץ',
}
ROWS['ca-valencia'] = ROWS['ca']
ROWS['es-x-chileno'] = ROWS['es']
ROWS['es-x-andaluz'] = ROWS['es']

CAPTION = 'The caption is attached to the first file. Photos and videos form an album; other mixed files are sent as documents.'
CAPTIONS = {
    'es': 'El texto se adjunta al primer archivo. Las fotos y los vídeos forman un álbum; las demás mezclas de archivos se envían como documentos.',
    'ru': 'Подпись прикрепляется к первому файлу. Фото и видео образуют альбом; остальные смешанные файлы отправляются как документы.',
    'pl': 'Podpis jest dołączany do pierwszego pliku. Zdjęcia i filmy tworzą album; inne mieszane pliki są wysyłane jako dokumenty.',
    'ca': 'El text s’adjunta al primer fitxer. Les fotos i els vídeos formen un àlbum; les altres combinacions de fitxers s’envien com a documents.',
    'uk': 'Підпис додається до першого файлу. Фото й відео утворюють альбом; інші змішані файли надсилаються як документи.',
    'zh-Hans': '说明附在第一个文件上。照片和视频组成相册；其他混合类型的文件作为文档发送。',
    'ko': '설명은 첫 번째 파일에 첨부됩니다. 사진과 동영상은 앨범으로 묶이며, 그 외의 혼합 파일은 문서로 전송됩니다.',
    'ja': 'キャプションは最初のファイルに添付されます。写真と動画はアルバムになり、その他の混在するファイルはドキュメントとして送信されます。',
    'it': 'La didascalia viene allegata al primo file. Foto e video formano un album; gli altri file misti vengono inviati come documenti.',
    'pt': 'A legenda é anexada ao primeiro arquivo. Fotos e vídeos formam um álbum; outras combinações de arquivos são enviadas como documentos.',
    'el': 'Η λεζάντα προστίθεται στο πρώτο αρχείο. Οι φωτογραφίες και τα βίντεο σχηματίζουν άλμπουμ· άλλα μικτά αρχεία αποστέλλονται ως έγγραφα.',
    'eu': 'Testua lehen fitxategiari eransten zaio. Argazkiek eta bideoek album bat osatzen dute; bestelako fitxategi nahasiak dokumentu gisa bidaltzen dira.',
    'gl': 'O texto engádese ao primeiro ficheiro. As fotos e os vídeos forman un álbum; as demais mesturas de ficheiros envíanse como documentos.',
    'oc-aran': 'Eth tèxte s’adjunh ath prumèr fichèr. Es fotos e es vidèos formen un àlbum; es autes combinacions de fichèrs s’envien coma documents.',
    'an': 'O texto s’adchunta a o primer fichero. As fotos y os vídeos forman un álbum; as demás mezclas de fichers se ninvian como documentos.',
    'de': 'Die Beschriftung wird der ersten Datei angehängt. Fotos und Videos bilden ein Album; andere gemischte Dateien werden als Dokumente gesendet.',
    'fr': 'La légende est jointe au premier fichier. Les photos et vidéos forment un album ; les autres fichiers mixtes sont envoyés comme documents.',
    'ar': 'يُرفق الوصف بالملف الأول. تشكّل الصور والفيديوهات ألبومًا؛ وتُرسل الملفات المختلطة الأخرى كمستندات.',
    'nl': 'Het bijschrift wordt aan het eerste bestand toegevoegd. Foto’s en video’s vormen een album; andere gemengde bestanden worden als documenten verstuurd.',
    'fi': 'Kuvateksti liitetään ensimmäiseen tiedostoon. Kuvat ja videot muodostavat albumin; muut sekoitetut tiedostot lähetetään asiakirjoina.',
    'be': 'Подпіс дадаецца да першага файла. Фота і відэа ўтвараюць альбом; іншыя змешаныя файлы адпраўляюцца як дакументы.',
    'ro': 'Descrierea este atașată primului fișier. Fotografiile și videoclipurile formează un album; celelalte fișiere mixte sunt trimise ca documente.',
    'sv': 'Bildtexten bifogas den första filen. Foton och videor bildar ett album; andra blandade filer skickas som dokument.',
    'nb': 'Bildeteksten legges ved den første filen. Bilder og videoer danner et album; andre blandede filer sendes som dokumenter.',
    'hi': 'कैप्शन पहली फ़ाइल से जुड़ता है। फ़ोटो और वीडियो एक एल्बम बनाते हैं; अन्य मिश्रित फ़ाइलें दस्तावेज़ों के रूप में भेजी जाती हैं।',
    'th': 'คำบรรยายแนบกับไฟล์แรก รูปภาพและวิดีโอรวมเป็นอัลบั้ม ส่วนไฟล์ประเภทอื่นที่ปะปนกันจะส่งเป็นเอกสาร',
    'bn': 'ক্যাপশনটি প্রথম ফাইলের সঙ্গে যুক্ত হয়। ছবি ও ভিডিও মিলে একটি অ্যালবাম হয়; অন্য মিশ্র ফাইলগুলো নথি হিসেবে পাঠানো হয়।',
    'fil': 'Idinadagdag ang caption sa unang file. Bumubuo ng album ang mga larawan at video; ipinapadala bilang mga dokumento ang iba pang magkakahalong file.',
    'ur': 'کیپشن پہلی فائل کے ساتھ منسلک ہوتا ہے۔ تصاویر اور ویڈیوز ایک البم بناتی ہیں؛ دوسری ملی جلی فائلیں دستاویزات کے طور پر بھیجی جاتی ہیں۔',
    'vi': 'Chú thích được đính kèm vào tệp đầu tiên. Ảnh và video tạo thành một album; các loại tệp hỗn hợp khác được gửi dưới dạng tài liệu.',
    'he': 'הכיתוב מצורף לקובץ הראשון. תמונות וסרטונים יוצרים אלבום; קבצים מעורבים אחרים נשלחים כמסמכים.',
}
CAPTIONS['ca-valencia'] = CAPTIONS['ca']
CAPTIONS['es-x-chileno'] = CAPTIONS['es']
CAPTIONS['es-x-andaluz'] = CAPTIONS['es']


def entries(language):
    return {**dict(zip(KEYS, ROWS[language].split('|'), strict=True)), CAPTION: CAPTIONS[language]}


def extend(catalogues):
    # Extended packs are files loaded lazily; their entries are bundled there.
    for language, catalogue in catalogues.items():
        if isinstance(catalogue, dict) and language in ROWS:
            catalogue.update(entries(language))
