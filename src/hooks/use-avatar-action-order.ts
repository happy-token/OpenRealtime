"use client";

import { useEffect, useRef, useState, type PointerEvent } from "react";
import { AVATAR_ACTION_ORDER_CHANGED, orderRoleActions, readAvatarActionOrder, rememberAvatarActionOrder } from "@/lib/role-action-preferences";

export function useAvatarActionOrder<T>(avatarId: string, actions: T[], getId: (action: T) => string) {
  const [order, setOrder] = useState<string[]>([]);
  const [draggingActionId, setDraggingActionId] = useState<string | null>(null);
  const [dropActionId, setDropActionId] = useState<string | null>(null);
  const dragRef = useRef<{ pointerId: number; actionId: string; x: number; y: number; active: boolean } | null>(null);
  const suppressClick = useRef(false);
  useEffect(() => {
    const refresh = () => setOrder(readAvatarActionOrder(avatarId));
    refresh();
    window.addEventListener(AVATAR_ACTION_ORDER_CHANGED, refresh);
    window.addEventListener("storage", refresh);
    return () => {
      window.removeEventListener(AVATAR_ACTION_ORDER_CHANGED, refresh);
      window.removeEventListener("storage", refresh);
    };
  }, [avatarId]);
  const orderedActions = orderRoleActions(actions, order, getId);
  const targetId = (event: PointerEvent<HTMLButtonElement>) => document.elementFromPoint(event.clientX, event.clientY)
    ?.closest<HTMLElement>("[data-action-sort-id]")?.dataset.actionSortId;
  function finish(event: PointerEvent<HTMLButtonElement>, cancelled = false) {
    const drag = dragRef.current;
    if (!drag || drag.pointerId !== event.pointerId) return;
    const target = targetId(event);
    if (!cancelled && drag.active && target && target !== drag.actionId) {
      const ids = orderedActions.map(getId);
      const from = ids.indexOf(drag.actionId);
      const to = ids.indexOf(target);
      if (from >= 0 && to >= 0) {
        ids.splice(from, 1);
        ids.splice(to, 0, drag.actionId);
        setOrder(ids);
        rememberAvatarActionOrder(avatarId, ids);
      }
    }
    suppressClick.current = drag.active && !cancelled;
    dragRef.current = null;
    setDraggingActionId(null);
    setDropActionId(null);
    if (event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId);
  }
  return {
    orderedActions, draggingActionId, dropActionId,
    consumeDragClick: () => { const suppressed = suppressClick.current; suppressClick.current = false; return suppressed; },
    pointerHandlers: (actionId: string) => ({
      onActionPointerDown: (event: PointerEvent<HTMLButtonElement>) => {
        if (event.button !== 0) return;
        suppressClick.current = false;
        dragRef.current = { pointerId: event.pointerId, actionId, x: event.clientX, y: event.clientY, active: false };
        event.currentTarget.setPointerCapture(event.pointerId);
      },
      onActionPointerMove: (event: PointerEvent<HTMLButtonElement>) => {
        const drag = dragRef.current;
        if (!drag || drag.pointerId !== event.pointerId) return;
        if (!drag.active && Math.hypot(event.clientX - drag.x, event.clientY - drag.y) < 8) return;
        drag.active = true;
        setDraggingActionId(drag.actionId);
        event.preventDefault();
        const target = targetId(event);
        setDropActionId(target && target !== drag.actionId ? target : null);
      },
      onActionPointerUp: (event: PointerEvent<HTMLButtonElement>) => finish(event),
      onActionPointerCancel: (event: PointerEvent<HTMLButtonElement>) => finish(event, true),
    }),
  };
}
