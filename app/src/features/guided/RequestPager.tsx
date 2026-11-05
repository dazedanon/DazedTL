import { Button } from "../../ui/Button";

/**
 * Which of a run's requests a reader shows, "Request 2 of 12", with
 * Previous and Next once there are several. `empty` names it while the
 * count is not known.
 */
export function RequestPager({
  index,
  total,
  empty = "",
  change,
}: {
  index: number;
  total: number;
  empty?: string;
  change: (index: number) => void;
}) {
  return (
    <div className="request-navigation">
      <span>
        {total
          ? `Request ${(index + 1).toLocaleString()} of ${total.toLocaleString()}`
          : empty}
      </span>
      {total > 1 && (
        <div className="actions">
          <Button
            variant="quiet"
            disabled={index === 0}
            onClick={() => change(index - 1)}
          >
            Previous
          </Button>
          <Button
            variant="quiet"
            disabled={index >= total - 1}
            onClick={() => change(index + 1)}
          >
            Next
          </Button>
        </div>
      )}
    </div>
  );
}
