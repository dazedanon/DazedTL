/**
 * A file name that keeps its ending visible when shortened, so names sharing
 * a long prefix, such as numbered images, stay distinguishable.
 */
export function FileName({
  name,
  className = "",
  title,
}: {
  name: string;
  className?: string;
  title?: string;
}) {
  // Keep the extension and the few characters before it, where numbered
  // names differ; a long extension-less name keeps its last characters.
  const dot = name.lastIndexOf(".");
  const ending = dot > 0 && name.length - dot <= 6 ? name.length - dot : 0;
  const split = Math.max(0, name.length - ending - 4);
  return (
    <span className={`file-name ${className}`} title={title ?? name}>
      <span className="file-name-head">{name.slice(0, split)}</span>
      <span className="file-name-tail">{name.slice(split)}</span>
    </span>
  );
}
