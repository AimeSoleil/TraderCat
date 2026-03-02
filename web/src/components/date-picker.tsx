"use client";

import * as React from "react";
import { CalendarIcon } from "lucide-react";
import { format, parseISO } from "date-fns";

import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Calendar } from "@/components/ui/calendar";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";

interface DatePickerProps {
  value: string | null; // ISO date string "YYYY-MM-DD"
  onChange: (date: string) => void;
  availableDates?: string[]; // ISO date strings that are selectable
  placeholder?: string;
  className?: string;
}

export function DatePicker({
  value,
  onChange,
  availableDates = [],
  placeholder = "Select date",
  className,
}: DatePickerProps) {
  const [open, setOpen] = React.useState(false);

  const selectedDate = value ? parseISO(value) : undefined;

  // Build a Set of available date strings for fast lookup
  const availableSet = React.useMemo(
    () => new Set(availableDates),
    [availableDates],
  );

  // Disable dates that are not in availableDates (if provided)
  const disabledMatcher = React.useCallback(
    (date: Date) => {
      if (availableDates.length === 0) return false;
      const iso = format(date, "yyyy-MM-dd");
      return !availableSet.has(iso);
    },
    [availableDates, availableSet],
  );

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button
          variant="outline"
          className={cn(
            "w-[180px] justify-start gap-2 text-left font-normal",
            !value && "text-muted-foreground",
            className,
          )}
        >
          <CalendarIcon className="h-4 w-4" />
          {selectedDate ? format(selectedDate, "MMM dd, yyyy") : placeholder}
        </Button>
      </PopoverTrigger>
      <PopoverContent className="w-auto p-0" align="end">
        <Calendar
          mode="single"
          selected={selectedDate}
          onSelect={(date) => {
            if (date) {
              onChange(format(date, "yyyy-MM-dd"));
              setOpen(false);
            }
          }}
          disabled={disabledMatcher}
          defaultMonth={selectedDate}
        />
      </PopoverContent>
    </Popover>
  );
}
