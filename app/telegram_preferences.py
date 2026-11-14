"""Per-mode delivery policy and editable safe Telegram text."""
import html
import re
import time

import notification_preferences as preferences

MODES = [('quick','Modo Rápido'),('detailed','Modo Detalhado'),('subtitle','Só legendar')]
EVENTS = [('started','Início do processamento'),('download','Download da mídia'),
          ('lyrics','Busca e conferência de letra'),('separation','Preparação do áudio e vocais'),
          ('transcription','Transcrição'),('translation','Tradução'),('review','Pedido de revisão'),
          ('render','Renderização'),('completed','Conclusão: texto ou legenda do vídeo'),
          ('video','Anexar vídeo ou prévia'),('links','Incluir links dos arquivos originais'),
          ('youtube','Publicação no YouTube'),('paused','Pausa'),('errors','Erros e avisos')]
TEXTS = {event: '🎬 Sal0 Karaokê · {modo}\n{titulo}\n{etapa}\n{tempo}\n{mensagem}' for event,_ in EVENTS}
TEXTS.update(completed='✅ {titulo}\n{modo} concluído.\nTempo: {tempo}\n{links}',
             video='🎥 {titulo}\n{modo}\nTempo: {tempo}\n{links}',
             links='{links}', youtube='▶️ {titulo} publicado no YouTube\n{link}')
VARIABLES = ['titulo','modo','etapa','progresso','tempo','links','link','mensagem']


def normalize(value=None):
    return preferences.normalize(value,MODES,EVENTS)


def metadata(policy):
    return {'notification_policy':normalize(policy),'notification_modes':MODES,
            'notification_events':EVENTS,'notification_defaults':TEXTS,'notification_variables':VARIABLES}


def contextualize(targets, mode, title, elapsed=0):
    return [{**target,'_mode':mode if mode in dict(MODES) else 'detailed',
             '_title':title,'_started':time.monotonic(),'_elapsed':elapsed} for target in targets]


def allowed(target, event):
    return preferences.allowed(normalize(target.get('notification_policy')),target.get('_mode','detailed'),event)


def message(target, event, original, progress='', elapsed=None, links='', link='', stage=''):
    if not allowed(target,event): return None
    mode = target.get('_mode','detailed')
    template = normalize(target.get('notification_policy'))['templates'][mode][event]
    seconds = elapsed if elapsed is not None else target.get('_elapsed',0)+max(0,time.monotonic()-target.get('_started',time.monotonic()))
    seconds = max(0,round(seconds)); hours,remainder=divmod(seconds,3600);minutes,seconds=divmod(remainder,60)
    plain_links = html.unescape(re.sub(r'<[^>]*>', '', links))
    values = {'titulo':target.get('_title','Vídeo'),'modo':dict(MODES)[mode],
              'etapa':stage or html.unescape(re.sub(r'<[^>]*>','',str(original).split('\n')[0])),
              'progresso':str(progress)+'%' if progress != '' else '',
              'tempo':f'{hours}h {minutes:02d}min {seconds:02d}s', 'links':plain_links, 'link':link}
    return preferences.render(template,values,original,html_values={'links':links} if links else None)
