MAIN = main

.PHONY: pdf clean

pdf:
	latexmk -pdf -interaction=nonstopmode $(MAIN).tex

clean:
	latexmk -C $(MAIN).tex
