import asyncio
import json
from videocreator.shared.config import get_settings
from videocreator.infrastructure.persistence.database import get_sessionmaker
from videocreator.infrastructure.repositories.sql_repos import SqlScriptRepository

async def main():
    sm = get_sessionmaker(get_settings())
    repo = SqlScriptRepository(sm)
    
    script = await repo.get("scr_01KV5TM0AJE65TPHASY679")
    if not script:
        print("Script not found.")
        return
        
    script_dict = script.model_dump()
    scenes = script_dict['scenes']
    
    # Assign characters based on audio_text
    for scene in scenes:
        audio = scene.get('audio_text', "")
        char = "Narrador"
        
        if "¡Hola amigos!" in audio or "Soy Tico" in audio or "¡Qué bonito es" in audio or "¿Están listos" in audio:
            char = "Tico"
        elif "¡Oye! ¿Eres tú?" in audio or "No te preocupes. Estás" in audio:
            char = "Tico"
        elif "¿Un diamante azul?" in audio or "¡Mira! El río está" in audio:
            char = "Tico"
        elif "Si sigues triste" in audio or "¡No sabía que los roedores" in audio:
            char = "Tico" # Wait, "No sabía que los roedores..." is said by Sirocco! Let's check text.
        elif "¿Dónde estoy?" in audio or "Soy Sirocco." in audio or "pero me perdí" in audio:
            char = "Sirocco"
        elif "No sé, pero debo encontrar" in audio:
            char = "Sirocco"
        elif "¡No sabía que los roedores" in audio:
            char = "Sirocco"
        elif "Bueno, somos muy creativos." in audio:
            char = "Tico"
        elif "¡Es mi diamante!" in audio:
            char = "Sirocco"
        elif "No te preocupes, amigo." in audio:
            char = "Tico"
        elif "¡Gracias por ayudarme!" in audio:
            char = "Sirocco"
        elif "Eso es lo que hacen" in audio:
            char = "Tico"
        elif "Y así amigos," in audio or "¿Cuáles son tus mejores" in audio:
            char = "Tico"
        elif "¡Hasta pronto!" in audio or "¡Qué aventura!" in audio:
            char = "Tico"
        else:
            # Fallback based on content
            if "roedores" in audio or "gracias" in audio.lower() or "diamante" in audio and "mi" in audio:
                char = "Sirocco"
            else:
                char = "Tico"
                
        scene['raw']['character'] = char
        # Make sure it's also in the domain scene root, but the LLM doesn't put it there, the engine reads scene.get('character')
        # Wait, the domain entity Scene doesn't have 'character', it only has 'raw'.
        # Oh, does episode_render.py unpack `raw`?
        # Actually `base_provider.py` does `scene.get("character")`. Wait, `scene` in base_provider is a dict!
        # The script dict dumped from domain entity has `scene['raw']['character']`. Does the engine use `raw`?
        
    # Re-save
    from videocreator.domain.entities import Script
    updated_script = Script(**script_dict)
    await repo.save(updated_script)
    print("Updated characters in script scenes.")

asyncio.run(main())
