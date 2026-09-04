# Separate Avatar asset management from creation

Avatar asset management and creation are independent pages connected by shared Avatar navigation. Management owns accepted assets and their readiness or maintenance state, while Avatar Studio owns creation drafts and guided generation tasks; keeping management as a modal inside creation made saved assets, unfinished candidates, and model preparation actions compete in one surface and obscured which state was authoritative.

Shared Avatar navigation is organized by responsibility and contains only two destinations: `资产管理` and `创建数字人`. Source-image creation, optional realtime binding creation, and repeatable action creation are stages within the unified Avatar creation flow rather than separate navigation destinations; an existing Avatar adds capabilities from its management detail without creating another top-level asset.
