# Prepare confirmed Avatar Actions independently

Avatar Studio creates and reviews one action at a time so the user can judge each LivePortrait result before acceptance, but every accepted `avatar_action_id` begins its own durable all-required-model preparation workflow. Preparation continues after navigation and does not block configuring the next action; Asset Management exposes each action's independent progress and failure recovery, and only actions whose required preparations are complete may be selected for a session.
