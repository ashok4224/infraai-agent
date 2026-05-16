import asyncio, sys
sys.path.insert(0, '/app')

async def main():
    from app.database import async_session
    from app.models.foundry_config import FoundryAgentConfig
    from sqlalchemy import select

    async with async_session() as db:
        # 1. Clear foundry_agent_name on notifier to skip jailbreak-triggering Foundry call
        result = await db.execute(select(FoundryAgentConfig).where(FoundryAgentConfig.role == 'notifier'))
        notifier = result.scalar_one_or_none()
        if notifier:
            notifier.foundry_agent_name = None
            print('Notifier Foundry call disabled (was triggering jailbreak filter)')

        # 2. Verify chat agent exists
        result2 = await db.execute(select(FoundryAgentConfig).where(FoundryAgentConfig.role == 'chat'))
        chat = result2.scalar_one_or_none()
        if not chat:
            from app.models.foundry_config import FoundryAgentConfig as FAC
            chat_agent = FAC(
                agent_name='infraai-chat',
                foundry_agent_name='infraai-chat',
                role='chat',
                pipeline_order=0,
                system_type='all',
                agent_line='workflow',
                is_optional=False,
                is_active=True,
                description='SRE assistant chat agent',
            )
            db.add(chat_agent)
            print('Chat agent added')
        else:
            print('Chat agent already present: ' + chat.agent_name)

        await db.commit()
        print('Done.')

asyncio.run(main())
