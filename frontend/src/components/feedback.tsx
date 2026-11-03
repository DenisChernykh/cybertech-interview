import { Badge } from "@/components/ui/badge"
import { statusName } from "@/lib/api"

export function Notice({ message }: { message: string }) {
  return message ? (
    <div className="notice" role="alert">
      {message}
    </div>
  ) : null
}
export function Loading() {
  return (
    <p className="muted loading" role="status">
      Загружаем…
    </p>
  )
}
export function Tag({ status }: { status: string }) {
  return (
    <Badge variant="outline" className={"status status-" + status}>
      {statusName[status] || status}
    </Badge>
  )
}
