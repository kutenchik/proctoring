"""Explicit teacher allowlist shared by server, student and descriptor-driven UI.

New TOML settings never enter this registry implicitly. Schema 3 adds optional
audio evidence. Complete v1/v2 policies migrate with recording off; unsupported
versions and missing saved values fail closed.
"""
from dataclasses import dataclass, asdict, replace
from functools import lru_cache
import math
from .domain import EventType

VERSION = 3
LANGUAGES = ('en', 'ru', 'kk')

@dataclass(frozen=True)
class Field:
    key: str
    mapping: str
    labels: tuple[str, str, str]
    group: str
    placement: str = 'advanced'
    type: str = 'number'
    minimum: float | None = None
    maximum: float | None = None
    step: float = .1
    unit: str = ''
    live: str = 'never'
    depends_on: str | None = None
    choices: tuple[str, ...] = ()

EVENTS = {
    'phone_visible': (EventType.PHONE_VISIBLE,),
    'phone_raised': (EventType.PHONE_RAISED,),
    'second_person': (EventType.SECOND_PERSON,),
    'gaze_deviation': (EventType.GAZE_DOWN, EventType.GAZE_LEFT, EventType.GAZE_RIGHT),
    'face_absent': (EventType.FACE_ABSENT,),
}
EVENT_LABELS = {
    'phone_visible': ('Phone visible', 'Телефон в кадре', 'Телефон көрінеді'),
    'phone_raised': ('Phone raised near face', 'Телефон возле лица', 'Бетке жақын телефон'),
    'second_person': ('Second person', 'Второй человек', 'Екінші адам'),
    'gaze_deviation': ('Gaze deviation', 'Отклонение взгляда', 'Көзқарастың ауытқуы'),
    'face_absent': ('Face absent', 'Лицо отсутствует', 'Бет көрінбейді'),
}
FIELDS = tuple(
    Field('events.'+key+'.enabled', 'event_rules.'+key, labels, 'events', 'basic', 'boolean', live='both')
    for key, labels in EVENT_LABELS.items()
) + tuple(
    Field('events.'+key+'.seconds', 'thresholds.'+key,
          (labels[0]+' duration', labels[1]+': длительность', labels[2]+': ұзақтығы'),
          'timing', minimum=.1, maximum=60, unit='seconds', live='both', depends_on='events.'+key+'.enabled')
    for key, labels in EVENT_LABELS.items()
) + (
    Field('clearing_seconds', 'clearing_seconds', ('Event clearing duration','Время завершения события','Оқиғаны аяқтау уақыты'), 'timing', minimum=.1, maximum=30, unit='seconds', live='both'),
    Field('audio.enabled','audio.enabled',('Microphone energy monitoring','Мониторинг энергии микрофона','Микрофон энергиясын бақылау'),'audio','basic','boolean',live='disable'),
    Field('snapshots_enabled','snapshots_enabled',('Event camera snapshots','Снимки событий с камеры','Камера оқиғаларының суреттері'),'evidence','basic','boolean',live='disable'),
    Field('audio.voice_duration_threshold','audio.voice_duration_threshold',('Audio activity duration','Длительность звуковой активности','Дыбыс белсенділігінің ұзақтығы'),'audio',minimum=.1,maximum=30,unit='seconds',depends_on='audio.enabled'),
    Field('audio.energy_threshold','audio.energy_threshold',('Energy threshold (not verified speech)','Порог энергии (не распознавание речи)','Энергия шегі (сөйлеуді тану емес)'),'audio',minimum=.001,maximum=1,step=.001,depends_on='audio.enabled'),
    Field('audio.adaptive_calibration','audio.adaptive_calibration',('Adaptive microphone calibration','Адаптивная калибровка микрофона','Микрофонды бейімдеп калибрлеу'),'audio',type='boolean',depends_on='audio.enabled'),
    Field('vision.phone_confidence','vision.phone_confidence',('Phone confidence threshold','Порог уверенности: телефон','Телефон сенімділігінің шегі'),'vision',minimum=.05,maximum=.95,step=.01),
    Field('vision.person_confidence','vision.person_confidence',('Person confidence threshold','Порог уверенности: человек','Адам сенімділігінің шегі'),'vision',minimum=.05,maximum=.95,step=.01),
    Field('vision.head_down_pitch_degrees','vision.head_down_pitch_degrees',('Downward head angle','Угол наклона головы вниз','Бастың төмен еңкею бұрышы'),'vision',minimum=5,maximum=60,step=1,unit='degrees',depends_on='events.gaze_deviation.enabled'),
    Field('identity.selfie_verification_enabled','identity.selfie_verification_enabled',('Geometric consistency (not biometric identification)','Геометрическое сходство (не биометрическая идентификация)','Геометриялық сәйкестік (биометриялық сәйкестендіру емес)'),'identity',type='boolean'),
    Field('identity.impersonation_threshold','identity.impersonation_threshold',('Geometric difference threshold','Порог геометрического различия','Геометриялық айырмашылық шегі'),'identity',minimum=.05,maximum=2,step=.01,depends_on='identity.selfie_verification_enabled'),
    Field('identity.periodic_check_interval_seconds','identity.periodic_check_interval_seconds',('Geometric check interval','Интервал геометрической проверки','Геометриялық тексеру аралығы'),'identity',minimum=5,maximum=300,step=1,unit='seconds',depends_on='identity.selfie_verification_enabled'),
)
LEGACY_KEYS = {f.key for f in FIELDS}
FIELDS += (
    Field('advanced.remote_enabled','advanced.remote_enabled',('Remote-access observations','Наблюдения удалённого доступа','Қашықтан қол жеткізуді бақылау'),'advanced_checks','basic','boolean'),
    Field('advanced.remote_interval_seconds','advanced.remote_interval_seconds',('Remote check interval','Интервал проверки удалённого доступа','Қашықтан қол жеткізуді тексеру аралығы'),'advanced_checks',minimum=5,maximum=60,step=1,unit='seconds',depends_on='advanced.remote_enabled'),
    Field('advanced.remote_confirmations','advanced.remote_confirmations',('Repeated remote observations','Повторные наблюдения удалённого доступа','Қашықтан қол жеткізудің қайталанған бақылаулары'),'advanced_checks',minimum=2,maximum=10,step=1,depends_on='advanced.remote_enabled'),
    Field('advanced.liveness_enabled','advanced.liveness_enabled',('Passive face liveness','Пассивная проверка живого лица','Беттің тірілігін пассивті тексеру'),'advanced_checks','basic','boolean'),
    Field('advanced.identity_model','advanced.identity_model',('Face model (verified local resources required)','Модель лица (нужны проверенные локальные ресурсы)','Бет моделі (тексерілген жергілікті ресурстар қажет)'),'advanced_checks',type='choice',choices=('Facenet512',),depends_on='advanced.identity_enabled'),
    Field('advanced.identity_enabled','advanced.identity_enabled',('Local face matching (Facenet512)','Локальное сравнение лиц (Facenet512)','Жергілікті бет салыстыру (Facenet512)'),'advanced_checks','basic','boolean'),
    Field('advanced.liveness_interval_seconds','advanced.liveness_interval_seconds',('Liveness interval','Интервал проверки живого лица','Тірілікті тексеру аралығы'),'advanced_checks',minimum=5,maximum=60,step=1,unit='seconds',depends_on='advanced.liveness_enabled'),
    Field('advanced.liveness_confirmations','advanced.liveness_confirmations',('Repeated liveness observations','Повторные наблюдения живого лица','Тіріліктің қайталанған бақылаулары'),'advanced_checks',minimum=3,maximum=10,step=1,depends_on='advanced.liveness_enabled'),
    Field('advanced.identity_interval_seconds','advanced.identity_interval_seconds',('Face matching interval','Интервал сравнения лиц','Бет салыстыру аралығы'),'advanced_checks',minimum=5,maximum=300,step=1,unit='seconds',depends_on='advanced.identity_enabled'),
    Field('advanced.identity_confirmations','advanced.identity_confirmations',('Repeated face mismatches','Повторные несовпадения лиц','Беттің қайталанған сәйкессіздіктері'),'advanced_checks',minimum=3,maximum=10,step=1,depends_on='advanced.identity_enabled'),
    Field('advanced.facenet_cosine_threshold','advanced.facenet_cosine_threshold',('Facenet512 cosine distance threshold','Порог косинусного расстояния Facenet512','Facenet512 косинус қашықтығының шегі'),'advanced_checks',minimum=.2,maximum=.4,step=.01,depends_on='advanced.identity_enabled'),
)
V2_KEYS = {f.key for f in FIELDS}
FIELDS += (
    Field('audio_evidence.enabled','audio_evidence.enabled',('Save audio evidence','Сохранять аудиоматериалы','Аудиоматериалдарды сақтау'),'audio','basic','boolean',depends_on='audio.enabled'),
    Field('audio_evidence.pre_seconds','audio_evidence.pre_seconds',('Audio before event','Аудио до события','Оқиғаға дейінгі аудио'),'audio',minimum=0,maximum=5,step=.5,unit='seconds',depends_on='audio_evidence.enabled'),
    Field('audio_evidence.post_seconds','audio_evidence.post_seconds',('Audio after event','Аудио после события','Оқиғадан кейінгі аудио'),'audio',minimum=1,maximum=8,step=.5,unit='seconds',depends_on='audio_evidence.enabled'),
)
BY_KEY = {f.key:f for f in FIELDS}

@lru_cache(maxsize=1)
def defaults():
    # Read values, never comments. Keep the server independent of CV/Qt imports.
    import tomllib
    from .runtime import resource_root
    with (resource_root()/'config/default.example.toml').open('rb') as stream:data=tomllib.load(stream)
    values={}
    for f in FIELDS:
        mapping=f.mapping
        if mapping.startswith('audio_evidence.'):
            from .audio.evidence import AudioEvidenceConfig
            values[f.key]=getattr(AudioEvidenceConfig(),mapping.split('.')[1]);continue
        if mapping.startswith('advanced.'):
            from .advanced.settings import AdvancedConfig
            values[f.key]=getattr(AdvancedConfig(),mapping.split('.')[1]);continue
        if mapping.startswith('event_rules.'):values[f.key]=True;continue
        if mapping.startswith('thresholds.'):mapping='events.'+mapping.split('.')[1]
        elif mapping=='clearing_seconds':mapping='events.clearing_seconds'
        elif mapping=='snapshots_enabled':mapping='storage.snapshots_enabled'
        elif mapping.startswith('identity.'):mapping='exam.'+mapping
        value=data
        for part in mapping.split('.'):value=value[part]
        values[f.key]=value
    return validate_values(values)

def values_from_config(config):
    values={}
    for f in FIELDS:
        if f.mapping.startswith('event_rules.'):
            values[f.key]=getattr(config, 'event_rules', {}).get(f.mapping.split('.')[1], True)
        elif f.mapping.startswith('thresholds.'):
            values[f.key]=config.thresholds[EVENTS[f.mapping.split('.')[1]][0]]
        else:
            value=config
            for part in f.mapping.split('.'): value=getattr(value,part)
            values[f.key]=value
    return values

def validate_values(values, *, complete=True):
    if not isinstance(values,dict) or set(values)-set(BY_KEY):
        raise ValueError('Unknown monitoring configuration field')
    if complete and set(values)!=set(BY_KEY):
        raise ValueError('Incomplete saved policy; explicit migration is required')
    clean={}
    for key,value in values.items():
        f=BY_KEY[key]
        if f.type=='boolean':
            if type(value) is not bool: raise ValueError(f'{f.labels[0]}: choose on or off')
        elif f.type=='choice':
            if type(value) is not str or value not in f.choices: raise ValueError('Unapproved model')
        elif type(value) not in (int,float) or not math.isfinite(value) or not f.minimum<=value<=f.maximum:
            raise ValueError(f'{f.labels[0]}: expected {f.minimum}–{f.maximum} {f.unit}')
        if key.endswith('_confirmations') and int(value)!=value: raise ValueError('Confirmation count must be an integer')
        clean[key]=value
    if complete and clean.get("audio_evidence.enabled") and not clean.get("audio.enabled"):
        raise ValueError("Audio evidence requires microphone monitoring")
    return clean

def validate_policy(policy):
    if isinstance(policy,dict) and policy.get('schema_version') == 2 and type(policy.get('schema_version')) is int:
        if set(policy.get('values',{})) != V2_KEYS: raise ValueError('Incomplete version-2 policy')
        policy={**policy,'schema_version':VERSION,'values':{**defaults(),**policy['values']}}
    if isinstance(policy,dict) and policy.get('schema_version') == 1 and type(policy.get('schema_version')) is int:
        if set(policy.get('values',{})) != LEGACY_KEYS: raise ValueError('Incomplete legacy policy')
        policy={**policy,'schema_version':VERSION,'values':{**defaults(),**policy['values']}}
    if not isinstance(policy,dict) or set(policy)!={'schema_version','values'} or type(policy['schema_version']) is not int or policy['schema_version']!=VERSION:
        raise ValueError('Unsupported monitoring policy version')
    return {'schema_version':VERSION,'values':validate_values(policy['values'])}

def default_policy(): return {'schema_version':VERSION,'values':dict(defaults())}

def descriptions_for(f):
    if f.key.startswith('audio_evidence.'):
        return ('Short event-triggered mono audio clips, not verified speech. Requires microphone monitoring and consent v5. Fixed before setup; maximum 15 seconds per clip.',
                'Короткие монофрагменты по событиям, не подтверждённая речь. Нужны мониторинг микрофона и согласие v5. До настройки; не более 15 секунд.',
                'Оқиға бойынша қысқа моно аудио, расталған сөйлеу емес. Микрофон бақылауы мен v5 келісімі қажет. Баптауға дейін; ең көбі 15 секунд.')
    if f.group=='advanced_checks' and not f.key.startswith('advanced.remote'):
        return ('Local Facenet512 / MiniFASNet review signals from the authorized camera. Requires offline verified resources and consent v4. No legal identity or replay-resistance guarantee. Fixed before setup.',
                'Локальные сигналы Facenet512 / MiniFASNet с разрешённой камеры. Требуются проверенные модели и согласие v4. Не удостоверяет личность и не гарантирует защиту от повторов. До настройки.',
                'Рұқсат етілген камерадан жергілікті Facenet512 / MiniFASNet белгілері. Тексерілген модельдер мен v4 келісімі қажет. Заңды тұлғаны не қайталаудан қорғанысты растамайды. Баптауға дейін.')
    if f.group=='advanced_checks':
        return ('Optional matched application and current RDP-session observations. Running applications are not proof of active control. Requires consent v4; fixed before setup.',
                'Необязательные наблюдения приложений и текущего сеанса RDP. Работающее приложение не доказывает управление. Требуется согласие v4; до настройки.',
                'Қолданба және ағымдағы RDP сеансын қосымша бақылау. Іске қосылған қолданба басқаруды дәлелдемейді. v4 келісімі қажет; баптауға дейін.')
    if f.key.startswith('events.') and f.key.endswith('.enabled'):
        return ('Creates review events for this category. Disabling it preserves past events and shared vision processing.',
                'Создаёт события этой категории для проверки. Отключение сохраняет историю и общую обработку видео.',
                'Осы санат бойынша тексеру оқиғаларын жасайды. Өшіру тарихты және ортақ бейне өңдеуді сақтайды.')
    if f.key.endswith('.seconds'):
        return ('Required sustained fresh evidence before an event is created; gaps do not count.',
                'Длительность непрерывных свежих наблюдений до события; пропуски не учитываются.',
                'Оқиғаға дейінгі үздіксіз жаңа бақылау ұзақтығы; үзілістер есептелмейді.')
    if f.key=='clearing_seconds':
        return ('Required clear observation period before closing an event. A live change starts new episodes.',
                'Время отсутствия признака до завершения события. Живое изменение начинает новые эпизоды.',
                'Оқиғаны жабу үшін белгісіз бақылау кезеңі. Тікелей өзгеріс жаңа эпизодтарды бастайды.')
    if f.key=='audio.enabled':
        return ('Detects microphone energy, not verified speech; no audio recording. Can only be disabled during an exam.',
                'Определяет энергию микрофона, не речь; звук не записывается. Во время экзамена можно только отключить.',
                'Микрофон энергиясын анықтайды, сөйлеуді емес; дыбыс жазылмайды. Емтиханда тек өшіруге болады.')
    if f.key=='snapshots_enabled':
        return ('Allows future event camera images under consent. Live disabling keeps existing evidence; re-enabling is prohibited.',
                'Разрешает будущие снимки событий при согласии. Отключение сохраняет материалы; повторное включение запрещено.',
                'Келісіммен болашақ оқиға суреттеріне рұқсат береді. Өшіру материалдарды сақтайды; қайта қосуға болмайды.')
    if f.key=='audio.energy_threshold':
        return ('Fallback RMS energy threshold; a successful microphone check or manual sensitivity may supersede it.',
                'Резервный порог RMS; успешная проверка микрофона или ручная чувствительность могут заменить его.',
                'Қосалқы RMS шегі; сәтті микрофон тексеруі немесе қолмен сезімталдық оны ауыстыруы мүмкін.')
    if f.key=='audio.adaptive_calibration':
        return ('Allows the local quiet/sound check to recommend an energy threshold. Does not change Windows microphone volume.',
                'Разрешает локальной проверке тишины/звука подобрать порог. Громкость микрофона Windows не меняется.',
                'Жергілікті тыныштық/дыбыс тексеруіне шек ұсынуға рұқсат береді. Windows микрофон деңгейі өзгермейді.')
    if f.key=='audio.voice_duration_threshold':
        return ('Accumulated above-threshold audio duration before an activity event; not a speech recognition result.',
                'Накопленная длительность звука выше порога до события; это не распознавание речи.',
                'Оқиғаға дейінгі шектен жоғары дыбыс ұзақтығы; бұл сөйлеуді тану нәтижесі емес.')
    if f.group=='vision':
        return ('Sets the selected vision decision threshold before setup. Other geometry, calibration and health gates remain active.',
                'Задаёт выбранный порог до настройки. Остальные проверки геометрии, калибровки и состояния сохраняются.',
                'Баптауға дейін таңдалған көру шегін орнатады. Басқа геометрия, калибрлеу және күй тексерістері сақталады.')
    return ('Optional comparison of face geometry with the reference, not verified biometric identity. Applied before setup.',
            'Необязательное сравнение геометрии лица с эталоном, не биометрическая идентификация. Применяется до настройки.',
            'Бет геометриясын эталонмен қосымша салыстыру, биометриялық сәйкестендіру емес. Баптауға дейін қолданылады.')


def catalog():
    groups={'events':('Event categories','Категории событий','Оқиға санаттары'),'timing':('Detection timing','Время обнаружения','Анықтау уақыты'),'audio':('Audio energy','Энергия звука','Дыбыс энергиясы'),'vision':('Vision','Зрение','Көру'),'identity':('Geometric consistency','Геометрическое сходство','Геометриялық сәйкестік'),'evidence':('Evidence','Материалы','Материалдар')}
    groups['advanced_checks']=('Additional checks','Дополнительные проверки','Қосымша тексерулер')
    fields=[]
    for f in FIELDS:
        descriptions=descriptions_for(f)
        fields.append({**asdict(f),'default':defaults()[f.key],'labels':dict(zip(LANGUAGES,f.labels)),
                       'descriptions':dict(zip(LANGUAGES,descriptions)),'component':'toggle' if f.type=='boolean' else 'select' if f.type=='choice' else 'number',
                       'teacher_editable':True,'active_editable':f.live!='never','subgroup':f.group,
                       'dependencies':[] if not f.depends_on else [{'key':f.depends_on,'equals':True}]})
    return {'schema_version':VERSION,'fields':fields,'groups':{k:dict(zip(LANGUAGES,v)) for k,v in groups.items()},'default':default_policy()}

def apply_policy(config, policy):
    values=validate_policy(policy)['values'];updates={};nested={};rules={};thresholds=dict(config.thresholds)
    for key,value in values.items():
        mapping=BY_KEY[key].mapping
        if mapping.startswith('event_rules.'): rules[mapping.split('.')[1]]=value
        elif mapping.startswith('thresholds.'):
            for event in EVENTS[mapping.split('.')[1]]: thresholds[event]=value
        elif '.' in mapping:
            group,field=mapping.split('.');nested.setdefault(group,{})[field]=value
        else:updates[mapping]=value
    for group,fields in nested.items():updates[group]=replace(getattr(config,group),**fields)
    return replace(config,**updates,thresholds=thresholds,event_rules=rules)

def live_patch(current, patch):
    current=validate_policy(current);patch=validate_values(patch,complete=False)
    if not patch:raise ValueError('Choose at least one live adjustment')
    for key,value in patch.items():
        mode=BY_KEY[key].live
        if mode=='never' or (mode=='disable' and value is not False):
            raise ValueError('This field cannot be enabled or changed during an attempt')
    return validate_policy({'schema_version':VERSION,'values':{**current['values'],**patch}})


def configure_events(controller, config):
    thresholds=dict(config.thresholds)
    if config.identity.selfie_verification_enabled:thresholds[EventType.IMPERSONATION_SUSPECTED]=.001
    if config.vision.accessories.earphone_detection_enabled:thresholds[EventType.EARPHONE_SUSPECTED]=.001
    disabled={event for key,kinds in EVENTS.items() if not config.event_rules.get(key,True) for event in kinds}
    changes=controller.events.configure_policy(thresholds,config.clearing_seconds,disabled)
    if changes:controller._write_events(changes)

def configure_admission(bridge, config):
    from .events import EventEngine
    c=bridge.controller
    c.config=config
    c.configure_advanced()
    configure_events(c,config)
    bridge.monitor.config=config.vision
    bridge.monitor.calibration.config=config.vision
    bridge.flow.config=config.vision
    bridge.monitor.configure_identity(config.identity)
    bridge.audio.stop()
    bridge.audio=bridge.audio_factory(config.audio,bridge.clock)
    c.audio=bridge.audio if config.audio.enabled else None
    c.audio_events=(EventEngine({EventType.VOICE_DETECTED:config.audio.voice_duration_threshold},config.clearing_seconds,
                    bridge.clock,max_observation_gap=.5,accumulate_sample_durations=True) if config.audio.enabled else None)

def apply_live(bridge, payload, command):
    c=bridge.controller
    if set(payload)!={'reason','patch','base_revision','revision'}:raise ValueError('Invalid policy command')
    if type(payload['base_revision']) is not int or type(payload['revision']) is not int:raise ValueError('Invalid revision')
    if payload['base_revision']!=bridge.policy_revision or payload['revision']!=bridge.policy_revision+1:raise ValueError('Stale policy revision')
    old=bridge.effective_policy;new=live_patch(old,payload['patch']);config=apply_policy(c.config,new)
    configure_events(c,config)
    if c.audio_events:
        changes=c.audio_events.configure_policy(c.audio_events.thresholds,config.clearing_seconds)
        if changes:c._write_audio_events(changes)
    if not config.audio.enabled and c.audio is not None:c.audio.stop();c.audio=None
    bridge.config=c.config=config;bridge.effective_policy=new;bridge.policy_revision=payload['revision']
    c._append({'record_kind':'lifecycle','event_type':'monitoring_policy_changed',
        'timestamp':bridge.clock.wall_time(),'old_policy':old,'new_policy':new,
        'revision':bridge.policy_revision,'reason':payload['reason'],'teacher_id':command['teacher_id'],'command_id':command['command_id']})
    return True
