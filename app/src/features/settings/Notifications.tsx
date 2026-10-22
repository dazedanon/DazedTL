import {
  chooseSound,
  notify,
  resetSound,
  saveNotifications,
  useNotifications,
} from "../../app/notifications";
import { useAction } from "../../state/useAction";
import { ActionBar } from "../../ui/ActionBar";
import { ActionControl } from "../../ui/ActionControl";
import { Button } from "../../ui/Button";
import { CheckField, CheckGroup, FieldRow } from "../../ui/FieldRow";
import { PageBody } from "../../ui/PageLayout";
import { PathInput } from "../../ui/PathInput";

/** How DazedTL calls the user back to the window; changes apply at once. */
export default function Notifications() {
  const settings = useNotifications();
  const chosen = settings.sound || settings.desktop || settings.phone;
  const action = useAction();
  const change = (value: Parameters<typeof saveNotifications>[0]) => {
    action.clear();
    void action.run(async () => saveNotifications(value), "", "save");
  };
  return (
    <>
      <PageBody>
        <CheckGroup
          id="notifications"
          label="When work finishes"
          help="After a translation or other step that takes a while, when work waits for your approval, and when your assistant hands back a task or needs you."
          stacked
        >
          <CheckField
            id="notifications-sound"
            label="Play a sound"
            checked={settings.sound}
            onChange={(sound) => change({ sound })}
          />
          <CheckField
            id="notifications-desktop"
            label="Show a desktop notification"
            help="Shown while DazedTL is in the background, and its taskbar entry lights up until you return."
            checked={settings.desktop}
            onChange={(desktop) => change({ desktop })}
          />
          <CheckField
            id="notifications-phone"
            label="Send to your phone"
            help="Through the free ntfy app, even while DazedTL is in front, as long as it stays open."
            checked={settings.phone}
            onChange={(phone) => change({ phone })}
          />
        </CheckGroup>
        {settings.sound && (
          <FieldRow
            id="notifications-file"
            label="Sound"
            help="Your own file plays for up to 10 seconds."
            error={action.key === "sound" ? action.error : ""}
          >
            {(control) => (
              <div className="notification-field">
                <PathInput
                  {...control}
                  readOnly
                  value={
                    settings.soundName === null
                      ? "Loading…"
                      : settings.soundName || "Chime"
                  }
                />
                <Button
                  disabled={action.busy}
                  onClick={() => void action.run(chooseSound, "", "sound")}
                >
                  Choose file…
                </Button>
                {settings.soundName && (
                  <Button
                    variant="quiet"
                    disabled={action.busy}
                    onClick={() => void action.run(resetSound, "", "sound")}
                  >
                    Use the chime
                  </Button>
                )}
              </div>
            )}
          </FieldRow>
        )}
        {settings.phone && (
          <FieldRow
            id="notifications-topic"
            label="Phone topic"
            help="Install the free ntfy app on your phone, tap +, and subscribe to this topic. Anyone who knows it can read these notifications."
          >
            {(control) => (
              <div className="notification-field">
                <input {...control} readOnly value={settings.topic} />
                <ActionControl
                  label="Copy"
                  inline
                  disabled={action.busy}
                  error={action.key === "topic" ? action.error : ""}
                  notice={action.key === "topic" ? action.notice : ""}
                  onClick={() =>
                    void action.run(
                      () => window.dazedtl.copyText(settings.topic),
                      "Copied.",
                      "topic",
                    )
                  }
                />
              </div>
            )}
          </FieldRow>
        )}
      </PageBody>
      <ActionBar feedback={<div className="feedback" role="status" />}>
        <ActionControl
          label="Test notification"
          disabled={action.busy || !chosen}
          disabledReason={
            chosen ? "" : "Choose a sound or a notification to send first."
          }
          pending={action.busy && action.key === "test"}
          pendingText="Sending…"
          error={["sound", "topic"].includes(action.key) ? "" : action.error}
          notice={action.key === "test" ? action.notice : ""}
          onClick={() =>
            void action.run(
              () =>
                notify(
                  {
                    title: "DazedTL",
                    lines: ["This is how DazedTL tells you work has finished."],
                  },
                  true,
                ),
              settings.desktop || settings.phone ? "Notification sent." : "",
              "test",
            )
          }
        />
      </ActionBar>
    </>
  );
}
