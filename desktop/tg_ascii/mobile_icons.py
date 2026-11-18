"""Discover original mobile launcher PNGs in Telegram's official repositories."""
import hashlib
import io
import json
from pathlib import Path
import urllib.parse
import urllib.request
from PIL import Image
from .preferences import read_json,write_json

REPOSITORIES={'iOS':('TelegramMessenger/Telegram-iOS','Telegram/Telegram-iOS'),
              'Android':('DrKLO/Telegram','TMessagesProj/src/main/res')}


def source_url(url):
    value=urllib.parse.urlsplit(url)
    if value.scheme!='https' or value.username or value.password or value.port not in (None,443):raise ValueError('Invalid source')
    allowed=any(value.path.startswith('/repos/'+repo+'/contents/') if value.hostname=='api.github.com'
                else value.path.startswith('/'+repo+'/') if value.hostname=='raw.githubusercontent.com' else False
                for repo,_ in REPOSITORIES.values())
    if not allowed:raise ValueError('Unexpected mobile icon source')
    return url


class Redirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,req,fp,code,msg,headers,newurl):
        source_url(newurl)
        return super().redirect_request(req,fp,code,msg,headers,newurl)


def fetch(url,limit=4*1024*1024):
    request=urllib.request.Request(source_url(url),headers={'User-Agent':'TG-ASCII-desktop','Accept':'application/vnd.github+json'})
    with urllib.request.build_opener(Redirect()).open(request,timeout=10) as response:
        source_url(response.geturl());payload=response.read(limit+1)
    if len(payload)>limit:raise ValueError('Icon source too large')
    return payload


def contents(repo,path):
    result=json.loads(fetch('https://api.github.com/repos/'+repo+'/contents/'+urllib.parse.quote(path,safe='/')))
    if not isinstance(result,list):raise ValueError('Invalid icon catalogue')
    return result


def candidates(platform):
    repo,base=REPOSITORIES[platform];root=contents(repo,base)
    if platform=='Android':
        folders=[item for item in root if item.get('type')=='dir' and item.get('name','').startswith('mipmap-') and 'dpi' in item['name'] and 'v' not in item['name']]
        rank={'mipmap-xxxhdpi':5,'mipmap-xxhdpi':4,'mipmap-xhdpi':3,'mipmap-hdpi':2,'mipmap-mdpi':1}
        folders.sort(key=lambda item:rank.get(item['name'],0),reverse=True)
        seen=set()
        for folder in folders[:2]:
            for item in contents(repo,folder['path']):
                name=item.get('name','')
                if name.endswith('.png') and 'launcher' in name and name not in seen and item.get('download_url'):
                    seen.add(name);yield name[:-4],item['download_url']
    else:
        folders=[item for item in root if item.get('type')=='dir' and item.get('name','') in ('AppIcons.xcassets','DefaultAppIcon.xcassets')]
        for folder in folders:
            for icon in contents(repo,folder['path']):
                if icon.get('type')!='dir' or not icon.get('name','').endswith('.appiconset'):continue
                files=contents(repo,icon['path'])
                images=[item for item in files if item.get('name','').lower().endswith('.png') and item.get('download_url')]
                if images:
                    # Largest compressed file normally contains the high-resolution artwork.
                    image=max(images,key=lambda item:item.get('size',0))
                    yield icon['name'].removesuffix('.appiconset'),image['download_url']


def load_mobile_icons(platform,directory):
    if platform not in REPOSITORIES:raise ValueError('Unknown platform')
    directory=Path(directory)/platform;directory.mkdir(parents=True,exist_ok=True)
    manifest=directory/'icons.json';saved=read_json(manifest,{})
    if not isinstance(saved,dict):saved={}
    choices=[(label,directory/name) for name,label in saved.items() if Path(name).name==name and name.startswith('mobile-') and (directory/name).is_file()]
    if choices:return choices
    failure=None
    try:
        for label,url in candidates(platform):
            try:
                payload=fetch(url)
                with Image.open(io.BytesIO(payload)) as image:
                    if image.format!='PNG' or min(image.size)<48 or max(image.size)>2048:continue
                    image.verify()
                target=directory/('mobile-'+hashlib.sha256(payload).hexdigest()[:24]+'.png')
                target.write_bytes(payload);choices.append((platform+' · '+label,target))
                if len(choices)>=32:break
            except (OSError,ValueError) as exc:failure=exc
    except (OSError,ValueError) as exc:failure=exc
    if not choices:raise OSError('Mobile icon catalogue unavailable') from failure
    write_json(manifest,{path.name:label for label,path in choices})
    return choices
