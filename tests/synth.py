"""SYNTHETIC test fixtures. Hand-written sentence pools recombined at random.

This exists only to exercise the pipeline in tests; none of it is, or may be
presented as, the real corpus (the real raw data comes from download.sh).
"""
import gzip
import json
import os
import random

HI = [
    "भारत एक विशाल देश है जहाँ अनेक भाषाएँ बोली जाती हैं।",
    "गंगा नदी हिमालय से निकलकर बंगाल की खाड़ी में मिलती है।",
    "किसान सुबह जल्दी उठकर अपने खेतों में काम करने जाते हैं।",
    "विद्यालय में बच्चों को पढ़ाई के साथ खेलकूद भी सिखाया जाता है।",
    "बारिश के मौसम में नदियों का जलस्तर तेज़ी से बढ़ जाता है।",
    "दिल्ली में हर साल लाखों पर्यटक लाल किला देखने आते हैं।",
    "हमारे पुस्तकालय में हज़ारों पुस्तकें और पत्रिकाएँ उपलब्ध हैं।",
    "स्वास्थ्य के लिए रोज़ सुबह टहलना बहुत लाभदायक माना जाता है।",
    "इस वर्ष फसल अच्छी होने से गाँव के लोग बहुत प्रसन्न हैं।",
    "रेलगाड़ी समय पर स्टेशन पहुँच गई और यात्री उतरने लगे।",
    "वैज्ञानिकों ने मंगल ग्रह पर पानी के नए संकेत खोजे हैं।",
    "त्योहारों के समय बाज़ार में बहुत रौनक और भीड़ रहती है।",
    "शिक्षक ने कक्षा में गणित के कठिन सवाल आसानी से समझाए।",
    "पहाड़ों की ठंडी हवा और हरियाली मन को शांति देती है।",
    "सरकार ने ग्रामीण इलाकों में नई सड़कें बनाने की घोषणा की है।",
    "मेरी दादी हर शाम हमें पुरानी कहानियाँ सुनाया करती थीं।",
    "क्रिकेट का मैच देखने के लिए पूरा शहर मैदान में जमा हो गया।",
    "नदी किनारे बसा यह छोटा सा कस्बा अपने मेले के लिए प्रसिद्ध है।",
    "बिजली की बचत करना हम सभी की साझा ज़िम्मेदारी है।",
    "कवि ने अपनी नई कविता में प्रकृति की सुंदरता का वर्णन किया।",
    "अस्पताल में मरीजों की देखभाल के लिए अनुभवी डॉक्टर तैनात हैं।",
    "विश्वविद्यालय ने इस साल नए पाठ्यक्रम शुरू करने का निर्णय लिया है।",
    "हवाई अड्डे पर सुरक्षा जाँच के कारण यात्रियों को देर तक रुकना पड़ा।",
    "संगीत सीखने के लिए नियमित अभ्यास और धैर्य की आवश्यकता होती है।",
    "शहर की सफाई व्यवस्था सुधारने के लिए नगर निगम ने अभियान चलाया।",
    "पुराने किले की दीवारों पर बनी नक्काशी आज भी लोगों को आकर्षित करती है।",
    "प्रधानाचार्य ने वार्षिक समारोह में मेधावी छात्रों को पुरस्कार दिए।",
    "समुद्र के किनारे बैठकर लहरों को गिनना बच्चों का प्रिय खेल है।",
    "इस पुल के बन जाने से दोनों गाँवों के बीच की दूरी आधी रह गई।",
    "रसोई में माँ ने ताज़ा सब्ज़ियों से स्वादिष्ट भोजन तैयार किया।",
]
HL = [
    "yaar kal ka match dekha kya, kya zabardast game tha",
    "mujhe nahi pata ki wo kab aayega lekin hum intezaar kar rahe hain",
    "aaj office mein bahut kaam tha isliye main late ghar pahuncha",
    "bhai tum sach mein bahut accha gaana gaate ho, mujhe pasand aaya",
    "kal subah meeting hai to please slides time par bhej dena",
    "ye phone bahut mehenga hai lekin camera ekdum mast hai",
    "mummy ne bola hai ki shaam ko sab log ghar pe khaana khayenge",
    "kya tum weekend pe movie dekhne chalna chahte ho, mera mann hai",
    "traffic itna zyada tha ki hum ek ghante tak fase rahe",
    "mera exam kal hai aur abhi tak maine kuch bhi nahi padha hai",
    "dost ne kaha ki wo is baar Goa jaane ka plan bana raha hai",
    "bahut din ho gaye tumse baat kiye, sab theek to hai na",
]
PROVERBS = ["जैसी करनी वैसी भरनी।", "अब पछताए होत क्या जब चिड़िया चुग गई खेत।", "नाच न जाने आँगन टेढ़ा।"]


def para(rng, pool, n):
    return " ".join(rng.choice(pool) for _ in range(n))


def make(raw_dir, seed=7):
    rng = random.Random(seed)
    d = os.path.join(raw_dir, "synth_news")
    os.makedirs(d, exist_ok=True)
    docs = []
    for i in range(300):
        docs.append({"id": f"n{i}", "text": para(rng, HI, rng.randint(3, 9)), "lang": "en"})  # wrong source label on purpose
    # exact + near duplicates
    docs.append(dict(docs[0], id="dup-exact"))
    base = docs[1]["text"]
    docs.append({"id": "near", "text": base + " " + rng.choice(HI)})
    docs.append({"id": "near-ws", "text": base.replace(" ", "  ", 2)})
    # PII
    docs.append({"id": "pii", "text": "संपर्क करें 98765 43210 या ravi.kumar@example.com पर। पैन ABCPK1234F और आधार 2345 6789 0123 है। " + para(rng, HI, 2)})
    docs.append({"id": "nonpii", "text": "इस वर्ष जनसंख्या 1234567890 थी और कीमत ₹1,50,000 रही, साल 2024 में। " + para(rng, HI, 2)})
    # junk
    docs += [
        {"id": "html", "text": "<div><p>" + para(rng, HI, 2) + "</p><script>x=1</script></div>"},
        {"id": "moji", "text": "à¤¹à¤¿à¤¨à¥à¤¦à¥€ à¤­à¤¾à¤·à¤¾ à¤¹à¥ˆ à¤¯à¤¹ à¤¬à¤¹à¥à¤¤ à¤…à¤šà¥à¤›à¥€"},
        {"id": "spam", "text": "Click here buy now free download casino betting lottery jackpot " * 5},
        {"id": "en", "text": "The quick brown fox jumps over the lazy dog and the river is wide."},
        {"id": "mr", "text": "हे पुस्तक आहे आणि ते मराठी भाषेत आहे. त्यांनी ते केले आणि मध्ये ठेवले."},
        {"id": "table", "text": "वर्ष  बिक्री  लाभ\n2019 120 30\n2020 135 33\n2021 150 41\n2022 170 52"},
        {"id": "proverb", "text": PROVERBS[0]},
        {"id": "poem", "text": "चाँद निकला रात आई\nतारे जगमग गीत गाए\nनींद आँखों में समाई\nसपने सारे पास आए"},
        {"id": "short", "text": "ठीक"},
        {"id": "empty", "text": "   "},
    ]
    with open(os.path.join(d, "news.jsonl"), "w", encoding="utf-8") as f:
        for i, dd in enumerate(docs):
            f.write(json.dumps(dd, ensure_ascii=False) + "\n")
            if i == 5:
                f.write("{this is not json\n")
                f.write("[1,2,3]\n")
                f.write(json.dumps({"id": "x", "text": None}) + "\n")
        f.write("\n")
    with open(os.path.join(d, "bad_bytes.jsonl"), "wb") as f:
        f.write(json.dumps({"text": para(rng, HI, 3)}, ensure_ascii=False).encode() + b"\n")
        f.write(b'{"text": "\xff\xfe broken"}\n')
        f.write(json.dumps({"text": para(rng, HI, 4)}, ensure_ascii=False).encode() + b"\n")
    d2 = os.path.join(raw_dir, "synth_chat")
    os.makedirs(d2, exist_ok=True)
    chat = [{"message": para(rng, HL, rng.randint(1, 3)), "label": "hi"} for _ in range(60)]
    chat.append({"message": "the weather is nice today and we are going to the park with friends"})
    with gzip.open(os.path.join(d2, "chat.jsonl.gz"), "wt", encoding="utf-8") as f:
        for c in chat:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")
    return raw_dir
