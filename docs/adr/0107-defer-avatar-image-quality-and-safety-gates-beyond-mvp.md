# Defer Avatar image quality and safety gates beyond MVP

The MVP saves the user-selected Avatar image without adding face detection, quality scoring, model-compatibility scanning, safety warnings, blocking validation, or a risk-acceptance step. Model-specific generation or session startup may still fail through its normal task error path when an input cannot be processed, but Avatar Studio does not predict or gate that outcome at image-save time. Existing request and object-storage constraints remain infrastructure boundaries and are not presented as a new image-review workflow.
