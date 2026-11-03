import { useId, useState, type FormEvent } from "react"
import { Dialog } from "radix-ui"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"

type Props = {
  open: boolean
  onOpenChange: (open: boolean) => void
  title: string
  description: string
  confirmLabel: string
  reasonLabel?: string
  busy: boolean
  error: string
  onConfirm: (reason: string) => Promise<boolean>
}

export default function ActionDialog({
  open,
  onOpenChange,
  title,
  description,
  confirmLabel,
  reasonLabel,
  busy,
  error,
  onConfirm,
}: Props) {
  const reasonId = useId()
  const [validationError, setValidationError] = useState("")
  function changeOpen(value: boolean) {
    if (busy) return
    setValidationError("")
    onOpenChange(value)
  }
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (busy) return
    const reason = String(new FormData(event.currentTarget).get("reason") || "").trim()
    if (reasonLabel && reason.length < 3) {
      setValidationError("Укажите причину — не менее 3 символов.")
      return
    }
    setValidationError("")
    if (await onConfirm(reason)) onOpenChange(false)
  }
  return (
    <Dialog.Root open={open} onOpenChange={changeOpen}>
      <Dialog.Portal>
        <Dialog.Overlay className="action-dialog-overlay" />
        <Dialog.Content className="action-dialog">
          <Dialog.Title className="action-dialog-title">{title}</Dialog.Title>
          <Dialog.Description className="action-dialog-description">
            {description}
          </Dialog.Description>
          <form onSubmit={submit}>
            {reasonLabel && (
              <div className="field">
                <Label htmlFor={reasonId}>{reasonLabel}</Label>
                <Input
                  id={reasonId}
                  name="reason"
                  required
                  minLength={3}
                  maxLength={500}
                  disabled={busy}
                />
              </div>
            )}
            {(validationError || error) && (
              <p className="notice" role="alert">
                {validationError || error}
              </p>
            )}
            <div className="action-dialog-buttons">
              <Dialog.Close asChild>
                <Button type="button" variant="outline" disabled={busy}>
                  Назад
                </Button>
              </Dialog.Close>
              <Button type="submit" disabled={busy}>
                {busy ? "Сохраняем…" : confirmLabel}
              </Button>
            </div>
          </form>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  )
}
