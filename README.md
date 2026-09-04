# feehost

`feehost` သည် Flask ဖြင့်ရေးထားသော RT777 web application ဖြစ်ပြီး Render တွင် deploy လုပ်ရန် ပြင်ဆင်ထားပါသည်။ အဓိက application file ကို `Rmmm.py` ဟု rename လုပ်ထားပြီး၊ Render start command က `gunicorn Rmmm:app` ကိုအသုံးပြုပါသည်။

## Render Deploy

GitHub repository ကို Render တွင် **New → Blueprint** မှတစ်ဆင့်ရွေးချယ်ပြီး `render.yaml` ကိုအသုံးပြုပါ။ Build command နှင့် start command များသည် YAML ထဲတွင် ထည့်ပြီးသားဖြစ်ပါသည်။

## Environment Variables

| Variable | လိုအပ်မှု | အဓိပ္ပာယ် |
|---|---:|---|
| `SECRET_KEY` | မဖြစ်မနေ | Flask session များကို sign/encrypt လုပ်ရန် secret key ဖြစ်သည်။ `render.yaml` က random value generate လုပ်ပေးပါသည်။ |
| `ADMIN_USERNAME` | မဖြစ်မနေ | Admin login username ဖြစ်သည်။ Render တွင် ကိုယ်တိုင်ထည့်ပါ။ |
| `ADMIN_PASSWORD` | မဖြစ်မနေ | Admin login password ဖြစ်သည်။ အားကောင်းသော password သုံးပြီး Render တွင် ကိုယ်တိုင်ထည့်ပါ။ |

Environment variable မထည့်ထားလျှင် source code ထဲရှိ default values (`admin1` နှင့် `change-me`) သို့ fallback ဖြစ်နိုင်သောကြောင့် production မတင်မီ Render Dashboard တွင် အထက်ပါ variables သုံးခုလုံးကို သေချာသတ်မှတ်ပါ။

## Local Run

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
export SECRET_KEY='replace-with-a-long-random-value'
export ADMIN_USERNAME='admin1'
export ADMIN_PASSWORD='replace-with-a-strong-password'
python Rmmm.py
```

ထို့နောက် `http://localhost:5000` ကိုဖွင့်ပါ။

## Important Storage Note

Application သည် SQLite database (`rt777.sqlite3`) နှင့် uploaded files များကို local filesystem ထဲတွင် သိမ်းပါသည်။ Render ရဲ့ ပုံမှန် web service filesystem သည် persistent database/file storage အဖြစ် မသင့်တော်သောကြောင့် service restart သို့မဟုတ် redeploy ဖြစ်သည့်အခါ data နှင့် uploads ပျောက်နိုင်ပါသည်။ Production အသုံးပြုမှုအတွက် persistent disk သို့မဟုတ် external database/object storage ကို နောက်ပိုင်းတွင် ထည့်သွင်းရန်လိုပါမည်။

## Included Files

- `Rmmm.py` — Flask application
- `requirements.txt` — Python dependencies
- `render.yaml` — Render Blueprint configuration
- `.gitignore` — local database, uploads, and secrets များကို Git ထဲမတင်ရန် rule များ
