# Remove single-frame pose editing from Avatar Action creation

Avatar Action creation accepts only continuous LivePortrait driving performances that produce reviewable loopable videos. The former parameter-control path produced a single pose image and could not satisfy the `avatar_action_id`, motion-video, loop-review, or Lip-sync Model Preparation contract, so it is removed from the action workflow; future single-image pose editing belongs to Avatar image editing rather than being presented as an action.
