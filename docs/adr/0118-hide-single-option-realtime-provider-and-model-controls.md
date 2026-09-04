# Hide single-option realtime Provider and model controls

The MVP labels its optional provider stage `实时驱动（Anam）` and does not render a selector containing only Anam. It queries models available to the configured Anam organization: one available model is used directly, while multiple models render a selector with the recommended version preselected. The Avatar binding schema remains provider-qualified so adding a second Provider can later replace the fixed label with Provider cards without changing `avatar_id` or existing Anam bindings.
