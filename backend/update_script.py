import asyncio
import json
import uuid
from videocreator.shared.config import get_settings
from videocreator.infrastructure.persistence.database import get_sessionmaker
from videocreator.infrastructure.repositories.sql_repos import SqlScriptRepository

async def main():
    sm = get_sessionmaker(get_settings())
    repo = SqlScriptRepository(sm)
    
    with open('dragon_script.json', 'r', encoding='utf-8') as f:
        data = json.load(f)
        
    scenes = data['scenes']
    new_scenes = []
    
    def duplicate_scene(scene, new_audio):
        new_sc = json.loads(json.dumps(scene))
        new_sc['id'] = "scn_" + uuid.uuid4().hex[:22].upper()
        new_sc['audio_text'] = new_audio
        new_sc['raw']['audio_text'] = new_audio
        new_sc['transition'] = "continue"
        new_sc['raw']['transition_to_next'] = "continue"
        return new_sc
        
    for scene in scenes:
        idx = scene['index']
        
        if idx == 0:
            s1 = scene
            s1['audio_text'] = "¡Hola amigos! Soy Tico y hoy van a conocer la aventura más emocionante que jamás habría vivido."
            s1['raw']['audio_text'] = s1['audio_text']
            s1['transition'] = "continue"
            s1['raw']['transition_to_next'] = "continue"
            new_scenes.append(s1)
            
            s2 = duplicate_scene(s1, "¿Están listos para un nuevo viaje?")
            s2['transition'] = "cut"
            s2['raw']['transition_to_next'] = "cut"
            new_scenes.append(s2)
            
        elif idx == 4:
            s1 = scene
            s1['audio_text'] = "Soy Sirocco. Mi casa está en la montaña cercana,"
            s1['raw']['audio_text'] = s1['audio_text']
            s1['transition'] = "continue"
            s1['raw']['transition_to_next'] = "continue"
            new_scenes.append(s1)
            
            s2 = duplicate_scene(s1, "pero me perdí al perseguir un brillante diamante azul que vi en el cielo.")
            s2['transition'] = "cut"
            s2['raw']['transition_to_next'] = "cut"
            new_scenes.append(s2)
            
        elif idx == 15:
            s1 = scene
            s1['audio_text'] = "Y así amigos, aprendí que ser amable y cuidadoso con los demás puede llevarnos a grandes aventuras."
            s1['raw']['audio_text'] = s1['audio_text']
            s1['transition'] = "continue"
            s1['raw']['transition_to_next'] = "continue"
            new_scenes.append(s1)
            
            s2 = duplicate_scene(s1, "¿Cuáles son tus mejores experiencias de ayudar a alguien?")
            s2['transition'] = "cut"
            s2['raw']['transition_to_next'] = "cut"
            new_scenes.append(s2)
            
        else:
            new_scenes.append(scene)
            
    # Re-index
    for i, sc in enumerate(new_scenes):
        sc['index'] = i
        
    data['scenes'] = new_scenes
    
    # Save to db
    script_id = data['id']
    script = await repo.get(script_id)
    if script:
        # Since domain entity uses model_validate on payload_json, we can dump, update and load
        from videocreator.domain.entities import Script
        script_dict = script.model_dump()
        script_dict.update(data)
        updated_script = Script(**script_dict)
        await repo.save(updated_script)
        print(f"Updated script {script_id} with new split scenes.")
    else:
        print("Script not found in DB.")

asyncio.run(main())
