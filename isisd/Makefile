# all: ALWAYS
# 	@$(MAKE) -s -C .. isisd/isisd

# all: ALWAYS isisd/isisd isis_tlvs

all: isis_tlvs

isis_tlvs: isis_tlvs.c
	gcc -Wall -o isis_tlvs isis_tlvs.c $(CFLAGS) $(LDFLAGS)

# %: ALWAYS
# 	@$(MAKE) -s -C .. isisd/$@

Makefile:
	#nothing
ALWAYS:
.PHONY: ALWAYS makefiles
.SUFFIXES:
