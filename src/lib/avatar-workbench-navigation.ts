export type AvatarWorkbenchTask = "avatar" | "motion" | "talking" | "realtime";

export type AvatarWorkbenchLocation = {
  task?: AvatarWorkbenchTask;
  avatarId?: string;
  actionId?: string;
  returnTo?: string;
  method?: "lipforcing";
};

export function avatarResourceHref(location: AvatarWorkbenchLocation = {}) {
  const params = new URLSearchParams({ tab: "avatars" });
  if (location.task) params.set("task", location.task);
  if (location.avatarId) params.set("avatar_id", location.avatarId);
  if (location.actionId) params.set("action_id", location.actionId);
  if (location.returnTo) params.set("return_to", location.returnTo);
  if (location.method) params.set("method", location.method);
  return `/resources?${params.toString()}`;
}
